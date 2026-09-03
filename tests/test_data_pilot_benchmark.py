from pathlib import Path

from data_pilot.benchmark import _answer_matches, run_benchmark, save_report


CASES = Path(__file__).resolve().parents[1] / "benchmarks" / "cases.json"


def test_local_benchmark_is_fully_reproducible(tmp_path: Path) -> None:
    report = run_benchmark(CASES)
    paths = save_report(report, tmp_path)

    assert report.case_count == 60
    assert report.metrics["query_execution_rate"] == 1.0
    assert report.metrics["expected_columns_rate"] == 1.0
    assert report.metrics["answer_accuracy"] == 1.0
    assert report.metrics["fallback_rate"] == 0.0
    assert report.metrics["chart_selection_rate"] == 1.0
    assert report.metrics["read_only_rate"] == 1.0
    assert all(path.exists() for path in paths.values())


def test_answer_metric_rejects_structurally_valid_but_wrong_results() -> None:
    assert not _answer_matches(
        ["month", "revenue"],
        ["month", "revenue"],
        [("2025-01", 100.0), ("2025-02", 120.0)],
        ["month", "sales_amount"],
        [("2025-01", 100.0), ("2025-02", 999.0)],
    )


def test_benchmark_supports_stratified_category_sampling() -> None:
    report = run_benchmark(CASES, sample_per_category=1)

    assert report.case_count == 7
    assert report.metrics["answer_accuracy"] == 1.0
