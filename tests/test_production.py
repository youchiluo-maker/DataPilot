from __future__ import annotations

from data_pilot.audit import AuditStore, RunRecord
from data_pilot.database import DemoDatabase
from data_pilot.llm_client import LLMClientError
from data_pilot.service import AnalysisService


class FailingLLMClient:
    def chat(self, messages, model=None, max_tokens=900):
        raise LLMClientError("timeout")


def test_audit_store_round_trips_run_records() -> None:
    store = AuditStore(":memory:")
    record = RunRecord(
        run_id="run-123",
        created_at="2026-09-01T00:00:00+00:00",
        question="查看订单状态",
        source="demo",
        model="local",
        status="success",
        duration_seconds=0.123,
        row_count=6,
        column_count=3,
        fallback_used=True,
        sql="SELECT status, COUNT(*) FROM orders",
        warnings=("model timeout",),
    )

    store.append(record)

    assert store.get("run-123") == record
    assert store.recent(1) == [record]


def test_analysis_service_adds_run_id_and_audits_success() -> None:
    store = AuditStore(":memory:")
    result = AnalysisService(
        DemoDatabase(), audit_store=store, source="test"
    ).analyze("查看订单状态分布")

    assert len(result.run_id) == 12
    assert result.source == "test"
    assert result.status == "success"
    assert result.fallback_used is False
    assert store.get(result.run_id) is not None


def test_analysis_service_marks_model_fallback() -> None:
    result = AnalysisService(
        DemoDatabase(),
        llm_client=FailingLLMClient(),
    ).analyze("查看订单状态分布")

    assert result.model == "local"
    assert result.fallback_used is True
    assert result.warnings


def test_analysis_service_audits_failed_question() -> None:
    store = AuditStore(":memory:")
    service = AnalysisService(DemoDatabase(), audit_store=store)

    try:
        service.analyze("   ")
    except RuntimeError:
        pass
    else:
        raise AssertionError("empty question should fail")

    records = store.recent()
    assert len(records) == 1
    assert records[0].status == "failed"
    assert records[0].error


def test_api_health_and_analysis_contract(monkeypatch, tmp_path) -> None:
    pytest = __import__("pytest")
    pytest.importorskip("fastapi")
    from fastapi.testclient import TestClient

    import api_app

    monkeypatch.setenv("DATAPILOT_AUDIT_DB", str(tmp_path / "audit.db"))
    monkeypatch.setenv("DEEPSEEK_API_KEY", "")
    monkeypatch.setenv("SILICONFLOW_API_KEY", "")
    api_app.get_service.cache_clear()
    client = TestClient(api_app.app)
    health = client.get("/healthz")
    assert health.status_code == 200
    assert health.json()["service"] == "datapilot"

    response = client.post("/v1/analyze", json={"question": "查看订单状态分布"})
    assert response.status_code == 200
    payload = response.json()
    assert payload["run_id"]
    assert payload["status"] == "success"
    assert payload["columns"]
    assert payload["evidence"]
    detail = client.get(f"/v1/runs/{payload['run_id']}")
    assert detail.status_code == 200
    assert detail.json()["question"] == "查看订单状态分布"
    assert client.get("/v1/runs/missing").status_code == 404


def test_api_token_guard(monkeypatch) -> None:
    pytest = __import__("pytest")
    pytest.importorskip("fastapi")
    from fastapi.testclient import TestClient

    import api_app

    monkeypatch.setenv("DATAPILOT_AUDIT_DB", ":memory:")
    monkeypatch.setenv("DEEPSEEK_API_KEY", "")
    monkeypatch.setenv("SILICONFLOW_API_KEY", "")
    api_app.get_service.cache_clear()
    monkeypatch.setenv("DATAPILOT_API_TOKEN", "expected")
    client = TestClient(api_app.app)
    assert client.get("/v1/runs").status_code == 401
    assert client.get("/v1/runs", headers={"X-API-Key": "expected"}).status_code == 200


def test_api_rejects_unapproved_model(monkeypatch, tmp_path) -> None:
    pytest = __import__("pytest")
    pytest.importorskip("fastapi")
    from fastapi.testclient import TestClient

    import api_app

    monkeypatch.setenv("DATAPILOT_AUDIT_DB", str(tmp_path / "audit.db"))
    monkeypatch.setenv("DEEPSEEK_API_KEY", "")
    monkeypatch.setenv("SILICONFLOW_API_KEY", "")
    monkeypatch.delenv("DATAPILOT_API_TOKEN", raising=False)
    api_app.get_service.cache_clear()
    client = TestClient(api_app.app)

    response = client.post(
        "/v1/analyze",
        json={"question": "查看订单状态分布", "model": "arbitrary-provider/model"},
    )
    assert response.status_code == 400


def test_api_can_fail_closed_when_token_is_required(monkeypatch) -> None:
    pytest = __import__("pytest")
    pytest.importorskip("fastapi")
    from fastapi.testclient import TestClient

    import api_app

    monkeypatch.setenv("DATAPILOT_REQUIRE_API_TOKEN", "true")
    monkeypatch.delenv("DATAPILOT_API_TOKEN", raising=False)
    client = TestClient(api_app.app)

    response = client.get("/v1/runs")
    assert response.status_code == 503
