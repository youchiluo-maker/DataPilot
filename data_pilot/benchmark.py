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
    chart_match: bool
    read_only: bool
    trace_complete: bool
    row_count: int
    latency_seconds: float
    error: str = ""
    actual_columns: list[str] = field(default_factory=list)


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
}


def _columns_match(expected: set[str], actual: list[str]) -> bool:
    raw_actual = {column.strip().lower() for column in actual}
    normalized_actual = set(raw_actual)
    normalized_actual.update(COLUMN_ALIASES.get(column, column) for column in raw_actual)
    normalized_expected = {column.strip().lower() for column in expected}
    return normalized_expected.issubset(normalized_actual)


def _metric_snapshot(cases: list[CaseResult]) -> dict[str, float]:
    if not cases:
        return {
            "query_execution_rate": 0.0,
            "nonempty_result_rate": 0.0,
            "expected_columns_rate": 0.0,
            "chart_selection_rate": 0.0,
            "read_only_rate": 0.0,
            "trace_completion_rate": 0.0,
            "average_latency_seconds": 0.0,
            "p95_latency_seconds": 0.0,
        }
    latencies = [case.latency_seconds for case in cases if case.executed]
    return {
        "query_execution_rate": _ratio(cases, "executed"),
        "nonempty_result_rate": _ratio(cases, "nonempty"),
        "expected_columns_rate": _ratio(cases, "columns_match"),
        "chart_selection_rate": _ratio(cases, "chart_match"),
        "read_only_rate": _ratio(cases, "read_only"),
        "trace_completion_rate": _ratio(cases, "trace_complete"),
        "average_latency_seconds": statistics.fmean(latencies) if latencies else 0.0,
        "p95_latency_seconds": _percentile(latencies, 0.95) if latencies else 0.0,
    }


def run_benchmark(
    cases_path: Path,
    *,
    agent_factory: Callable[[], DataPilotAgent] | None = None,
    mode: str = "local-template",
    limit: int | None = None,
) -> BenchmarkReport:
    cases = load_cases(cases_path)
    if limit is not None:
        if limit <= 0:
            raise ValueError("评测案例数量必须大于 0。")
        cases = cases[:limit]
    raw = json.dumps(cases, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    results: list[CaseResult] = []

    for case in cases:
        try:
            agent = agent_factory() if agent_factory is not None else DataPilotAgent(DemoDatabase())
            result = agent.analyze(str(case["question"]))
            expected_columns = set(case.get("expected_columns", []))
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
                    chart_match=result.chart_type == case.get("expected_chart"),
                    read_only=read_only,
                    trace_complete=len(result.trace) >= 5,
                    row_count=len(result.rows),
                    latency_seconds=result.duration_seconds,
                    actual_columns=result.columns,
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
        f"| 图表选择准确率 | {m['chart_selection_rate']:.0%} |",
        f"| 只读 SQL 通过率 | {m['read_only_rate']:.0%} |",
        f"| 执行轨迹完整率 | {m['trace_completion_rate']:.0%} |",
        f"| 平均延迟 | {m['average_latency_seconds']:.4f} s |",
        f"| P95 延迟 | {m['p95_latency_seconds']:.4f} s |",
        "",
        "指标由固定问题集自动计算；切换 mode 后可直接比较本地模板与模型规划的差异。",
        "",
        "## 分组指标",
        "",
        "| 分组 | 执行率 | 字段命中 | 图表命中 | 只读 | P95 延迟 |",
        "|---|---:|---:|---:|---:|---:|",
    ]
    for name, segment in sorted(report.segments.items()):
        lines.append(
            f"| {name} | {segment['query_execution_rate']:.0%} | "
            f"{segment['expected_columns_rate']:.0%} | "
            f"{segment['chart_selection_rate']:.0%} | "
            f"{segment['read_only_rate']:.0%} | "
            f"{segment['p95_latency_seconds']:.4f} s |"
        )
    lines.extend(
        [
            "",
            "## 案例",
            "",
            "| ID | 执行 | 字段 | 图表 | 只读 | 行数 | 延迟 | 实际字段 |",
            "|---|---:|---:|---:|---:|---:|---:|---|",
        ]
    )
    for case in report.cases:
        lines.append(
            f"| {case.case_id} | {'通过' if case.executed else '失败'} | "
            f"{'通过' if case.columns_match else '失败'} | "
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
