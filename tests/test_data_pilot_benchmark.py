from pathlib import Path

from data_pilot.benchmark import run_benchmark, save_report


CASES = Path(__file__).resolve().parents[1] / "benchmarks" / "cases.json"


def test_local_benchmark_is_fully_reproducible(tmp_path: Path) -> None:
    report = run_benchmark(CASES)
    paths = save_report(report, tmp_path)

    assert report.case_count == 60
    assert report.metrics["query_execution_rate"] == 1.0
    assert report.metrics["expected_columns_rate"] == 1.0
    assert report.metrics["chart_selection_rate"] == 1.0
    assert report.metrics["read_only_rate"] == 1.0
    assert all(path.exists() for path in paths.values())
