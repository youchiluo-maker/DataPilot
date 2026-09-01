from __future__ import annotations

import argparse
from pathlib import Path

from data_pilot.agent import DataPilotAgent
from data_pilot.benchmark import run_benchmark, save_report
from data_pilot.config import load_settings
from data_pilot.database import DemoDatabase
from data_pilot.llm_client import DeepSeekClient


PROJECT_ROOT = Path(__file__).resolve().parent


def main() -> None:
    parser = argparse.ArgumentParser(description="运行 DataPilot 固定问题集评测")
    parser.add_argument(
        "--mode",
        choices=("local", "model"),
        default="local",
        help="local 使用离线模板；model 调用已配置的 DeepSeek",
    )
    parser.add_argument(
        "--model",
        default=None,
        help="模型 ID，默认读取 DEEPSEEK_MODEL",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="只运行前 N 条案例，适合先做模型 smoke test",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=PROJECT_ROOT / "benchmark_results",
        help="评测报告输出目录",
    )
    args = parser.parse_args()

    cases_path = PROJECT_ROOT / "benchmarks" / "cases.json"
    if args.mode == "model":
        settings = load_settings()
        client = DeepSeekClient(settings)
        model = args.model or settings.default_model
        factory = lambda: DataPilotAgent(
            DemoDatabase(), llm_client=client, model=model
        )
        mode = f"deepseek:{model}"
    else:
        factory = None
        mode = "local-template"

    report = run_benchmark(
        cases_path,
        agent_factory=factory,
        mode=mode,
        limit=args.limit,
    )
    paths = save_report(report, args.output_dir)
    print(f"完成 {report.case_count} 个评测案例，模式：{report.mode}。")
    for name, path in paths.items():
        print(f"{name}: {path}")
    print("核心指标：")
    for name in (
        "query_execution_rate",
        "expected_columns_rate",
        "chart_selection_rate",
        "read_only_rate",
        "p95_latency_seconds",
    ):
        print(f"  {name}: {report.metrics[name]}")


if __name__ == "__main__":
    main()
