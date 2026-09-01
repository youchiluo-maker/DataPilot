from __future__ import annotations

from dataclasses import asdict, dataclass, field
import json
import re
import time
from typing import Any

import pandas as pd

from .llm_client import DeepSeekClient, LLMClientError

from .database import DemoDatabase, QueryExecutionError, SQLSafetyError


class DataAgentError(RuntimeError):
    """Raised when the agent cannot produce a usable analysis."""


class QueryContractError(RuntimeError):
    """Raised when a model query runs but omits fields needed for the question."""


@dataclass(frozen=True)
class QueryPlan:
    sql: str
    chart_type: str = "table"
    title: str = "查询结果"
    reasoning: str = ""
    source: str = "local"


@dataclass
class AnalysisResult:
    question: str
    sql: str
    executed_sql: str
    chart_type: str
    title: str
    reasoning: str
    columns: list[str]
    rows: list[tuple[Any, ...]]
    summary: str
    trace: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    model: str = "local-template"
    duration_seconds: float = 0.0
    run_id: str = ""
    source: str = "demo"
    status: str = "success"
    fallback_used: bool = False
    error: str = ""

    def dataframe(self) -> pd.DataFrame:
        return pd.DataFrame(self.rows, columns=self.columns)

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["rows"] = [list(row) for row in self.rows]
        return payload


SYSTEM_PROMPT = """你是 DataPilot 的 SQL 分析规划器。你的任务是把用户的业务问题转换为一个安全、可执行的 SQLite 查询计划。

硬性要求：
1. 只能输出一个 JSON 对象，不要 Markdown 代码块，不要额外解释。
2. JSON 字段必须包含：sql、chart_type、title、reasoning。
3. sql 只能是单条 SELECT 或 WITH 查询，禁止 INSERT、UPDATE、DELETE、DROP、ALTER、PRAGMA 等操作。
4. 只能使用提供的表和字段；不要臆造数据。
5. chart_type 只能是 line、bar、table、none 之一。
6. reasoning 只说明查询思路，不要虚构查询结果。
"""


REPAIR_PROMPT = """你是 DataPilot 的 SQL 修复器。上一次查询已经通过了文本安全检查，但 SQLite 执行失败。
请根据数据库结构、用户问题、失败 SQL 和错误信息，修复查询并只输出一个 JSON 对象。

硬性要求：
1. JSON 字段必须包含：sql、chart_type、title、reasoning。
2. sql 只能是单条 SELECT 或 WITH 查询，只能访问提供的表和字段。
3. 禁止任何写操作、管理操作、多语句和臆造字段。
4. chart_type 只能是 line、bar、table、none 之一。
5. 不要解释过程，不要输出 Markdown 代码块。
"""


class DataPilotAgent:
    def __init__(
        self,
        database: DemoDatabase,
        llm_client: DeepSeekClient | None = None,
        model: str = "deepseek-ai/DeepSeek-V4-Pro",
    ):
        self.database = database
        self.llm_client = llm_client
        self.model = model

    def analyze(self, question: str) -> AnalysisResult:
        if not question or not question.strip():
            raise DataAgentError("问题不能为空。")

        started = time.perf_counter()
        question = question.strip()
        trace = ["解析用户问题。", "读取数据库 Schema 和字段说明。"]
        warnings: list[str] = []

        plan = self._model_plan(question, trace, warnings)
        if plan is None:
            plan = self._local_plan(question)
            trace.append("使用本地查询模板生成可复现的分析计划。")
        else:
            trace.append(f"模型生成查询计划：{self.model}。")

        try:
            trace.append("执行 SQL 只读安全检查。")
            query = self.database.execute_read_only(plan.sql)
            self._validate_model_contract(question, plan, query.columns)
        except (SQLSafetyError, QueryExecutionError, QueryContractError) as exc:
            warnings.append(f"模型计划未通过安全检查或执行失败：{exc}")
            repaired = None
            if plan.source == "model" and isinstance(
                exc, (QueryExecutionError, QueryContractError)
            ):
                trace.append("模型 SQL 执行失败，发起一次受限修复重试。")
                repaired = self._model_repair(question, plan, exc, trace, warnings)
            if repaired is not None:
                try:
                    trace.append("执行修复后的 SQL 只读安全检查。")
                    query = self.database.execute_read_only(repaired.sql)
                    self._validate_model_contract(question, repaired, query.columns)
                    plan = repaired
                    trace.append("修复后的模型计划执行成功。")
                except (SQLSafetyError, QueryExecutionError, QueryContractError) as repair_exc:
                    warnings.append(f"修复后的模型计划仍不可执行：{repair_exc}")
                    repaired = None
            if repaired is None:
                trace.append("模型计划不可执行，切换到本地安全模板重试。")
                fallback = self._local_plan(question)
                query = self.database.execute_read_only(fallback.sql)
                plan = QueryPlan(
                    sql=fallback.sql,
                    chart_type=fallback.chart_type,
                    title=fallback.title,
                    reasoning=fallback.reasoning,
                    source="local-fallback",
                )

        trace.append(f"完成只读查询，返回 {len(query.rows)} 行、{len(query.columns)} 列。")
        summary = self._summarize(question, plan, query.columns, query.rows)
        trace.append("根据真实查询结果生成摘要和图表建议。")
        return AnalysisResult(
            question=question,
            sql=plan.sql,
            executed_sql=query.sql,
            chart_type=plan.chart_type,
            title=plan.title,
            reasoning=plan.reasoning,
            columns=query.columns,
            rows=query.rows,
            summary=summary,
            trace=trace,
            warnings=warnings,
            model=self.model if plan.source in {"model", "model-repair"} else plan.source,
            duration_seconds=time.perf_counter() - started,
        )

    def _model_plan(
        self, question: str, trace: list[str], warnings: list[str]
    ) -> QueryPlan | None:
        if self.llm_client is None:
            return None
        messages = [
            {"role": "system", "content": SYSTEM_PROMPT},
            {
                "role": "user",
                "content": f"数据库结构：\n{self.database.schema_text}\n\n用户问题：{question}",
            },
        ]
        try:
            raw = self.llm_client.chat(messages, model=self.model, max_tokens=900)
            return self._plan_from_json(self._parse_json(raw), source="model")
        except (LLMClientError, DataAgentError, json.JSONDecodeError, TypeError, ValueError) as exc:
            warnings.append(f"模型规划不可用，已使用本地模式：{exc}")
            trace.append("模型规划失败，准备降级到本地模式。")
            return None

    def _model_repair(
        self,
        question: str,
        failed_plan: QueryPlan,
        error: Exception,
        trace: list[str],
        warnings: list[str],
    ) -> QueryPlan | None:
        """Ask the model once to repair a syntactically invalid but read-only query."""
        if self.llm_client is None:
            return None
        messages = [
            {"role": "system", "content": REPAIR_PROMPT},
            {
                "role": "user",
                "content": (
                    f"数据库结构：\n{self.database.schema_text}\n\n"
                    f"用户问题：{question}\n\n"
                    f"失败 SQL：\n{failed_plan.sql}\n\n"
                    f"SQLite 错误：{error}"
                ),
            },
        ]
        try:
            raw = self.llm_client.chat(messages, model=self.model, max_tokens=700)
            repaired = self._plan_from_json(self._parse_json(raw), source="model-repair")
            trace.append("模型返回了修复计划。")
            return repaired
        except (LLMClientError, DataAgentError, json.JSONDecodeError, TypeError, ValueError) as exc:
            warnings.append(f"模型修复不可用：{exc}")
            trace.append("模型修复失败，准备使用本地安全模板。")
            return None

    def _validate_model_contract(
        self, question: str, plan: QueryPlan, columns: list[str]
    ) -> None:
        if plan.source not in {"model", "model-repair"}:
            return
        if not self.database.template_mode:
            return
        required = self._required_columns(question)
        if not required:
            return
        aliases = {
            "sales": "revenue",
            "sales_amount": "revenue",
            "total_sales": "revenue",
            "amount": "total_amount",
            "orders": "order_count",
            "order_num": "order_count",
            "count": "order_count",
            "refunds": "refund_count",
            "refund_rate": "refund_rate_pct",
            "rate": "refund_rate_pct",
            "category_name": "category",
            "product_name": "product",
        }
        normalized = {aliases.get(column.lower(), column.lower()) for column in columns}
        if "revenue" in required:
            if "total_amount" in normalized:
                normalized.add("revenue")
            if "amount" in normalized:
                normalized.add("revenue")
        missing = sorted(required - normalized)
        if missing:
            raise QueryContractError(
                f"查询结果缺少问题所需字段：{', '.join(missing)}。"
            )

    @staticmethod
    def _required_columns(question: str) -> set[str]:
        q = question.lower()
        if ("退款" in q or "退货" in q) and ("月" in q or "月份" in q):
            return {"month", "refund_count", "refund_rate_pct"}
        if "品类" in q or "类别" in q:
            required = {"category"}
            if "销量" in q or "售出" in q:
                required.add("units_sold")
            if "销售" in q or "收入" in q or "金额" in q:
                required.add("revenue")
            if "订单" in q:
                required.add("order_count")
            return required
        if "状态" in q:
            required = {"status", "order_count"}
            if "金额" in q or "销售" in q or "收入" in q:
                required.add("total_amount")
            return required
        if "商品" in q or "产品" in q or "销量" in q:
            required = {"product"}
            if "销量" in q or "售出" in q:
                required.add("units_sold")
            if "销售" in q or "收入" in q or "金额" in q:
                required.add("revenue")
            return required
        if "月" in q or "趋势" in q or "销售额" in q or "订单金额" in q:
            required = {"month"}
            if "订单" in q:
                required.add("order_count")
            if "销售" in q or "收入" in q or "金额" in q:
                required.add("revenue")
            return required
        return set()

    @staticmethod
    def _plan_from_json(payload: dict[str, Any], *, source: str) -> QueryPlan:
        sql = str(payload.get("sql", "")).strip()
        chart_type = str(payload.get("chart_type", "table")).lower()
        if chart_type not in {"line", "bar", "table", "none"}:
            chart_type = "table"
        if not sql:
            raise DataAgentError("模型没有返回 SQL。")
        return QueryPlan(
            sql=sql,
            chart_type=chart_type,
            title=str(payload.get("title") or "查询结果"),
            reasoning=str(payload.get("reasoning") or "模型根据 Schema 规划了只读查询。"),
            source=source,
        )

    @staticmethod
    def _parse_json(raw: str) -> dict[str, Any]:
        cleaned = raw.strip()
        fenced = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", cleaned, flags=re.S | re.I)
        if fenced:
            cleaned = fenced.group(1)
        start = cleaned.find("{")
        end = cleaned.rfind("}")
        if start < 0 or end <= start:
            raise DataAgentError("模型返回中没有找到 JSON 对象。")
        payload = json.loads(cleaned[start : end + 1])
        if not isinstance(payload, dict):
            raise DataAgentError("模型返回的 JSON 顶层结构不是对象。")
        return payload

    def _local_plan(self, question: str) -> QueryPlan:
        if not self.database.template_mode:
            table = self.database.fallback_table
            return QueryPlan(
                sql=f'SELECT * FROM "{table}" LIMIT 20',
                chart_type="table",
                title=f"{table} 数据预览",
                reasoning=(
                    "自定义数据需要模型结合动态 Schema 规划查询；当前先返回首个数据表的安全预览。"
                ),
            )
        q = question.lower()
        if ("退款" in q or "退货" in q) and ("月" in q or "月份" in q):
            return QueryPlan(
                sql="""
WITH monthly AS (
    SELECT substr(order_date, 1, 7) AS month,
           COUNT(*) AS order_count,
           ROUND(SUM(total_amount), 2) AS revenue
    FROM orders
    WHERE status <> 'cancelled'
    GROUP BY substr(order_date, 1, 7)
), refund_monthly AS (
    SELECT substr(refund_date, 1, 7) AS month,
           COUNT(*) AS refund_count,
           ROUND(SUM(amount), 2) AS refund_amount
    FROM refunds
    GROUP BY substr(refund_date, 1, 7)
)
SELECT monthly.month,
       monthly.order_count,
       monthly.revenue,
       COALESCE(refund_monthly.refund_count, 0) AS refund_count,
       ROUND(COALESCE(refund_monthly.refund_count, 0) * 100.0 / monthly.order_count, 2) AS refund_rate_pct
FROM monthly
LEFT JOIN refund_monthly ON monthly.month = refund_monthly.month
ORDER BY monthly.month
""",
                chart_type="line",
                title="月度订单金额与退款率",
                reasoning="按月份聚合有效订单和退款记录，计算退款订单数占订单数的比例。",
            )
        if "品类" in q or "类别" in q:
            return QueryPlan(
                sql="""
SELECT p.category AS category,
       COUNT(DISTINCT o.id) AS order_count,
       SUM(oi.quantity) AS units_sold,
       ROUND(SUM(oi.quantity * oi.unit_price), 2) AS revenue
FROM orders o
JOIN order_items oi ON oi.order_id = o.id
JOIN products p ON p.id = oi.product_id
WHERE o.status <> 'cancelled'
GROUP BY p.category
ORDER BY revenue DESC
""",
                chart_type="bar",
                title="各品类销售表现",
                reasoning="关联订单明细和商品品类，按品类统计订单数、销量和销售额。",
            )
        if "状态" in q:
            return QueryPlan(
                sql="""
SELECT status, COUNT(*) AS order_count,
       ROUND(SUM(total_amount), 2) AS total_amount
FROM orders
GROUP BY status
ORDER BY order_count DESC
""",
                chart_type="bar",
                title="订单状态分布",
                reasoning="按订单状态分组，统计订单量和金额。",
            )
        if "商品" in q or "产品" in q or "销量" in q:
            return QueryPlan(
                sql="""
SELECT p.name AS product,
       SUM(oi.quantity) AS units_sold,
       ROUND(SUM(oi.quantity * oi.unit_price), 2) AS revenue
FROM order_items oi
JOIN products p ON p.id = oi.product_id
JOIN orders o ON o.id = oi.order_id
WHERE o.status <> 'cancelled'
GROUP BY p.id, p.name
ORDER BY units_sold DESC
LIMIT 10
""",
                chart_type="bar",
                title="热销商品 Top 10",
                reasoning="从订单明细汇总商品销量，并排除已取消订单。",
            )
        if "月" in q or "趋势" in q or "销售额" in q or "订单金额" in q:
            return QueryPlan(
                sql="""
SELECT substr(order_date, 1, 7) AS month,
       COUNT(*) AS order_count,
       ROUND(SUM(total_amount), 2) AS revenue
FROM orders
WHERE status <> 'cancelled'
GROUP BY substr(order_date, 1, 7)
ORDER BY month
""",
                chart_type="line",
                title="月度销售趋势",
                reasoning="按月份聚合有效订单数和销售额，观察业务趋势。",
            )
        return QueryPlan(
            sql="""
SELECT o.id AS order_id, o.order_date, o.status,
       ROUND(o.total_amount, 2) AS total_amount,
       u.region
FROM orders o
JOIN users u ON u.id = o.user_id
ORDER BY o.order_date DESC, o.id DESC
LIMIT 20
""",
            chart_type="table",
            title="最近订单",
            reasoning="问题未匹配到聚合模板，先返回最近订单作为可检查的数据切片。",
        )

    @staticmethod
    def _summarize(
        question: str, plan: QueryPlan, columns: list[str], rows: list[tuple[Any, ...]]
    ) -> str:
        if not rows:
            return "查询成功，但没有返回记录。可以扩大时间范围或检查筛选条件。"
        frame = pd.DataFrame(rows, columns=columns)
        numeric = frame.select_dtypes(include="number").columns.tolist()
        pieces = [f"本次分析返回 {len(frame)} 行、{len(columns)} 列。"]
        if numeric:
            first_numeric = numeric[0]
            series = pd.to_numeric(frame[first_numeric], errors="coerce").dropna()
            if not series.empty:
                pieces.append(
                    f"指标 {first_numeric} 的范围为 {series.min():,.2f} 到 {series.max():,.2f}。"
                )
        if plan.chart_type in {"line", "bar"}:
            pieces.append(f"已根据查询计划生成{plan.title}图表，详细 SQL 和原始结果见下方。")
        else:
            pieces.append("当前结果更适合以明细表查看，详细 SQL 和原始结果见下方。")
        return " ".join(pieces)
