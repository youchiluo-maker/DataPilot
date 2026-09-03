from __future__ import annotations

import csv
from dataclasses import asdict, dataclass, field
from datetime import datetime
import hashlib
import json
import math
from pathlib import Path
import statistics
from typing import Any, Callable

from .agent import DataPilotAgent
from .database import DemoDatabase, validate_read_only_sql


@dataclass
class CaseResult:
    case_id: str
    question: str
    executed: bool
    nonempty: bool
    columns_match: bool
    answer_match: bool
    chart_match: bool
    read_only: bool
    trace_complete: bool
    row_count: int
    latency_seconds: float
    error: str = ""
    actual_columns: list[str] = field(default_factory=list)
    executed_sql: str = ""
    fallback_used: bool = False
    warnings: list[str] = field(default_factory=list)


@dataclass
class BenchmarkReport:
    generated_at: str
    case_count: int
    cases_sha256: str
    metrics: dict[str, float]
    cases: list[CaseResult]
    mode: str = "local-template"
    segments: dict[str, dict[str, float]] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "generated_at": self.generated_at,
            "case_count": self.case_count,
            "cases_sha256": self.cases_sha256,
            "metrics": self.metrics,
            "mode": self.mode,
            "segments": self.segments,
            "cases": [asdict(case) for case in self.cases],
        }


def load_cases(path: Path) -> list[dict[str, Any]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, list) or not payload:
        raise ValueError("评测集必须是非空 JSON 数组。")
    return payload


def _ratio(cases: list[CaseResult], field: str) -> float:
    return sum(bool(getattr(case, field)) for case in cases) / len(cases)


def _percentile(values: list[float], percentile: float) -> float:
    ordered = sorted(values)
    index = max(0, math.ceil(percentile * len(ordered)) - 1)
    return ordered[index]


COLUMN_ALIASES = {
    "sales": "revenue",
    "sales_amount": "revenue",
    "total_sales": "revenue",
    "total_amount": "revenue",
    "amount": "total_amount",
    "orders": "order_count",
    "order_num": "order_count",
    "count": "order_count",
    "refunds": "refund_count",
    "refund_rate": "refund_rate_pct",
    "rate": "refund_rate_pct",
    "category_name": "category",
    "product_name": "product",
    "id": "order_id",
}


EXPECTED_COLUMN_CANDIDATES = {
    "month": ("month",),
    "order_count": ("order_count", "orders", "order_num", "count"),
    "revenue": ("revenue", "sales", "sales_amount", "total_sales", "total_amount"),
    "refund_count": ("refund_count", "refunds"),
    "refund_rate_pct": ("refund_rate_pct", "refund_rate", "rate"),
    "category": ("category", "category_name"),
    "units_sold": ("units_sold", "quantity", "sales_volume"),
    "status": ("status",),
    "total_amount": ("total_amount", "amount"),
    "order_share_pct": ("order_share_pct", "order_ratio", "order_percentage"),
    "amount_share_pct": ("amount_share_pct", "amount_ratio", "amount_percentage"),
    "product": ("product", "product_name"),
    "order_id": ("order_id", "id"),
    "order_date": ("order_date",),
    "region": ("region",),
}


def _columns_match(expected: set[str], actual: list[str]) -> bool:
    raw_actual = {column.strip().lower() for column in actual}
    normalized_actual = set(raw_actual)
    normalized_actual.update(COLUMN_ALIASES.get(column, column) for column in raw_actual)
    normalized_expected = {column.strip().lower() for column in expected}
    return normalized_expected.issubset(normalized_actual)


def _oracle_sql(case: dict[str, Any]) -> str:
    """Return a trusted query that represents the intended answer for one case."""
    category = str(case.get("category", "fallback"))
    question = str(case.get("question", ""))
    if category == "trend":
        return """
SELECT substr(order_date, 1, 7) AS month,
       COUNT(*) AS order_count,
       ROUND(SUM(total_amount), 2) AS revenue
FROM orders
WHERE status IN ('paid', 'shipped', 'completed')
GROUP BY substr(order_date, 1, 7)
ORDER BY month
"""
    if category == "refund":
        return """
WITH monthly AS (
    SELECT substr(order_date, 1, 7) AS month,
           COUNT(*) AS order_count,
           ROUND(SUM(total_amount), 2) AS revenue
    FROM orders
    WHERE status IN ('paid', 'shipped', 'completed')
    GROUP BY substr(order_date, 1, 7)
), refund_monthly AS (
    SELECT substr(refund_date, 1, 7) AS month,
           COUNT(*) AS refund_count
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
"""
    if category == "category":
        return """
SELECT p.category AS category,
       COUNT(DISTINCT o.id) AS order_count,
       SUM(oi.quantity) AS units_sold,
       ROUND(SUM(oi.quantity * oi.unit_price), 2) AS revenue
FROM orders o
JOIN order_items oi ON oi.order_id = o.id
JOIN products p ON p.id = oi.product_id
WHERE o.status IN ('paid', 'shipped', 'completed')
GROUP BY p.category
ORDER BY revenue DESC
"""
    if category == "status":
        where_clause = ""
        if all(keyword in question for keyword in ("已支付", "待支付", "已取消")):
            where_clause = "WHERE status IN ('paid', 'pending', 'cancelled')"
        select_suffix = ""
        if "占比" in question:
            select_suffix = """,
       ROUND(COUNT(*) * 100.0 / SUM(COUNT(*)) OVER (), 2) AS order_share_pct,
       ROUND(SUM(total_amount) * 100.0 / SUM(SUM(total_amount)) OVER (), 2) AS amount_share_pct"""
        return f"""
SELECT status, COUNT(*) AS order_count,
       ROUND(SUM(total_amount), 2) AS total_amount{select_suffix}
FROM orders
{where_clause}
GROUP BY status
ORDER BY order_count DESC
"""
    if category == "product":
        order_metric = (
            "revenue"
            if "销售额最高" in question or "收入最高" in question
            else "units_sold"
        )
        return f"""
SELECT p.name AS product,
       SUM(oi.quantity) AS units_sold,
       ROUND(SUM(oi.quantity * oi.unit_price), 2) AS revenue
FROM order_items oi
JOIN products p ON p.id = oi.product_id
JOIN orders o ON o.id = oi.order_id
WHERE o.status IN ('paid', 'shipped', 'completed')
GROUP BY p.id, p.name
ORDER BY {order_metric} DESC
LIMIT 10
"""
    return """
SELECT o.id AS order_id, o.order_date, o.status,
       ROUND(o.total_amount, 2) AS total_amount,
       u.region
FROM orders o
JOIN users u ON u.id = o.user_id
ORDER BY o.order_date DESC, o.id DESC
"""


def _normalize_value(value: Any) -> tuple[str, Any]:
    if value is None:
        return ("none", None)
    if isinstance(value, bool):
        return ("bool", value)
    if isinstance(value, (int, float)):
        return ("number", round(float(value), 6))
    return ("text", str(value))


def _project_rows(
    required_columns: list[str],
    source_columns: list[str],
    source_rows: list[tuple[Any, ...]],
) -> list[tuple[tuple[str, Any], ...]] | None:
    source_lookup = {
        column.strip().lower(): index for index, column in enumerate(source_columns)
    }
    indexes: list[int] = []
    for required in required_columns:
        candidates = EXPECTED_COLUMN_CANDIDATES.get(
            required.lower(), (required.lower(),)
        )
        source_index = next(
            (
                source_lookup[candidate]
                for candidate in candidates
                if candidate in source_lookup
            ),
            None,
        )
        if source_index is None:
            return None
        indexes.append(source_index)
    return [
        tuple(_normalize_value(row[index]) for index in indexes)
        for row in source_rows
    ]


def _answer_matches(
    required_columns: list[str],
    expected_columns: list[str],
    expected_rows: list[tuple[Any, ...]],
    actual_columns: list[str],
    actual_rows: list[tuple[Any, ...]],
    mode: str = "exact",
) -> bool:
    expected = _project_rows(required_columns, expected_columns, expected_rows)
    actual = _project_rows(required_columns, actual_columns, actual_rows)
    if expected is None or actual is None or not actual:
        return False
    if mode == "contains_top":
        return bool(expected) and expected[0] in actual
    if mode == "subset":
        return set(actual).issubset(set(expected))
    if mode == "prefix":
        return actual == expected[: len(actual)]
    return sorted(actual, key=repr) == sorted(expected, key=repr)


def _metric_snapshot(cases: list[CaseResult]) -> dict[str, float]:
    if not cases:
        return {
            "query_execution_rate": 0.0,
            "nonempty_result_rate": 0.0,
            "expected_columns_rate": 0.0,
            "answer_accuracy": 0.0,
            "chart_selection_rate": 0.0,
            "read_only_rate": 0.0,
            "trace_completion_rate": 0.0,
            "fallback_rate": 0.0,
            "average_latency_seconds": 0.0,
            "p95_latency_seconds": 0.0,
        }
    latencies = [case.latency_seconds for case in cases if case.executed]
    return {
        "query_execution_rate": _ratio(cases, "executed"),
        "nonempty_result_rate": _ratio(cases, "nonempty"),
        "expected_columns_rate": _ratio(cases, "columns_match"),
        "answer_accuracy": _ratio(cases, "answer_match"),
        "chart_selection_rate": _ratio(cases, "chart_match"),
        "read_only_rate": _ratio(cases, "read_only"),
        "trace_completion_rate": _ratio(cases, "trace_complete"),
        "fallback_rate": _ratio(cases, "fallback_used"),
        "average_latency_seconds": statistics.fmean(latencies) if latencies else 0.0,
        "p95_latency_seconds": _percentile(latencies, 0.95) if latencies else 0.0,
    }


def run_benchmark(
    cases_path: Path,
    *,
    agent_factory: Callable[[], DataPilotAgent] | None = None,
    mode: str = "local-template",
    limit: int | None = None,
    sample_per_category: int | None = None,
) -> BenchmarkReport:
    cases = load_cases(cases_path)
    if limit is not None and sample_per_category is not None:
        raise ValueError("limit 和 sample_per_category 不能同时使用。")
    if limit is not None:
        if limit <= 0:
            raise ValueError("评测案例数量必须大于 0。")
        cases = cases[:limit]
    if sample_per_category is not None:
        if sample_per_category <= 0:
            raise ValueError("每类抽样数量必须大于 0。")
        grouped: dict[str, list[dict[str, Any]]] = {}
        for case in cases:
            grouped.setdefault(str(case.get("category", "未分类")), []).append(case)
        cases = [
            case
            for category in sorted(grouped)
            for case in grouped[category][:sample_per_category]
        ]
    raw = json.dumps(cases, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    results: list[CaseResult] = []

    for case in cases:
        try:
            agent = agent_factory() if agent_factory is not None else DataPilotAgent(DemoDatabase())
            result = agent.analyze(str(case["question"]))
            required_columns = [str(column) for column in case.get("expected_columns", [])]
            expected_columns = set(required_columns)
            oracle = agent.database.execute_read_only(_oracle_sql(case))
            read_only = True
            try:
                validate_read_only_sql(result.executed_sql)
            except ValueError:
                read_only = False
            results.append(
                CaseResult(
                    case_id=str(case["id"]),
                    question=str(case["question"]),
                    executed=True,
                    nonempty=bool(result.rows),
                    columns_match=_columns_match(expected_columns, result.columns),
                    answer_match=_answer_matches(
                        required_columns,
                        oracle.columns,
                        oracle.rows,
                        result.columns,
                        result.rows,
                        str(case.get("answer_mode", "exact")),
                    ),
                    chart_match=result.chart_type == case.get("expected_chart"),
                    read_only=read_only,
                    trace_complete=len(result.trace) >= 5,
                    row_count=len(result.rows),
                    latency_seconds=result.duration_seconds,
                    actual_columns=result.columns,
                    executed_sql=result.executed_sql,
                    fallback_used=(
                        result.model in {"local", "local-fallback", "policy-fallback"}
                        and mode != "local-template"
                    ),
                    warnings=result.warnings,
                )
            )
        except Exception as exc:
            results.append(
                CaseResult(
                    case_id=str(case.get("id", "unknown")),
                    question=str(case.get("question", "")),
                    executed=False,
                    nonempty=False,
                    columns_match=False,
                    answer_match=False,
                    chart_match=False,
                    read_only=False,
                    trace_complete=False,
                    row_count=0,
                    latency_seconds=0.0,
                    error=str(exc),
                )
            )

    metrics = _metric_snapshot(results)
    segments: dict[str, dict[str, float]] = {}
    for field_name in ("category", "difficulty"):
        values = {str(case.get(field_name, "未分类")) for case in cases}
        for value in sorted(values):
            segment_cases = [
                result
                for result, case in zip(results, cases)
                if str(case.get(field_name, "未分类")) == value
            ]
            segments[f"{field_name}:{value}"] = _metric_snapshot(segment_cases)
    return BenchmarkReport(
        generated_at=datetime.now().astimezone().isoformat(timespec="seconds"),
        case_count=len(results),
        cases_sha256=hashlib.sha256(raw).hexdigest(),
        metrics=metrics,
        cases=results,
        mode=mode,
        segments=segments,
    )


def render_markdown(report: BenchmarkReport) -> str:
    m = report.metrics
    lines = [
        f"# DataPilot 评测报告（{report.mode}）",
        "",
        f"- 生成时间：{report.generated_at}",
        f"- 案例数量：{report.case_count}",
        f"- 评测集 SHA-256：`{report.cases_sha256}`",
        "",
        "## 指标",
        "",
        "| 指标 | 结果 |",
        "|---|---:|",
        f"| 查询执行率 | {m['query_execution_rate']:.0%} |",
        f"| 非空结果率 | {m['nonempty_result_rate']:.0%} |",
        f"| 预期字段命中率 | {m['expected_columns_rate']:.0%} |",
        f"| 结果集正确率 | {m['answer_accuracy']:.0%} |",
        f"| 图表选择准确率 | {m['chart_selection_rate']:.0%} |",
        f"| 只读 SQL 通过率 | {m['read_only_rate']:.0%} |",
        f"| 执行轨迹完整率 | {m['trace_completion_rate']:.0%} |",
        f"| 降级率 | {m['fallback_rate']:.0%} |",
        f"| 平均延迟 | {m['average_latency_seconds']:.4f} s |",
        f"| P95 延迟 | {m['p95_latency_seconds']:.4f} s |",
        "",
        "指标由固定问题集自动计算；切换 mode 后可直接比较本地模板与模型规划的差异。",
        "",
        "## 分组指标",
        "",
        "| 分组 | 执行率 | 字段命中 | 结果正确 | 图表命中 | 只读 | P95 延迟 |",
        "|---|---:|---:|---:|---:|---:|---:|",
    ]
    for name, segment in sorted(report.segments.items()):
        lines.append(
            f"| {name} | {segment['query_execution_rate']:.0%} | "
            f"{segment['expected_columns_rate']:.0%} | "
            f"{segment['answer_accuracy']:.0%} | "
            f"{segment['chart_selection_rate']:.0%} | "
            f"{segment['read_only_rate']:.0%} | "
            f"{segment['p95_latency_seconds']:.4f} s |"
        )
    lines.extend(
        [
            "",
            "## 案例",
            "",
            "| ID | 执行 | 字段 | 结果 | 图表 | 只读 | 行数 | 延迟 | 实际字段 |",
            "|---|---:|---:|---:|---:|---:|---:|---:|---|",
        ]
    )
    for case in report.cases:
        lines.append(
            f"| {case.case_id} | {'通过' if case.executed else '失败'} | "
            f"{'通过' if case.columns_match else '失败'} | "
            f"{'通过' if case.answer_match else '失败'} | "
            f"{'通过' if case.chart_match else '失败'} | "
            f"{'通过' if case.read_only else '失败'} | {case.row_count} | "
            f"{case.latency_seconds:.4f} s | {', '.join(case.actual_columns)} |"
        )
    return "\n".join(lines) + "\n"


def save_report(report: BenchmarkReport, output_dir: Path) -> dict[str, Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    json_path = output_dir / "latest.json"
    csv_path = output_dir / "latest.csv"
    markdown_path = output_dir / "latest.md"
    json_path.write_text(
        json.dumps(report.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8"
    )
    markdown_path.write_text(render_markdown(report), encoding="utf-8")
    with csv_path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(asdict(report.cases[0]).keys()))
        writer.writeheader()
        writer.writerows(asdict(case) for case in report.cases)
    return {"json": json_path, "csv": csv_path, "markdown": markdown_path}
