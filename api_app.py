from __future__ import annotations

import os
import logging
import secrets
from functools import lru_cache
from typing import Annotated

from fastapi import Depends, FastAPI, Header, HTTPException, status
from pydantic import BaseModel, Field

from data_pilot.agent import DataAgentError
from data_pilot.audit import AuditStore
from data_pilot.config import load_settings
from data_pilot.database import DemoDatabase, QueryExecutionError, SQLSafetyError
from data_pilot.llm_client import DeepSeekClient
from data_pilot.service import AnalysisService


logger = logging.getLogger("datapilot.api")


class AnalyzeRequest(BaseModel):
    question: str = Field(min_length=1, max_length=2000)
    model: str | None = None


class AnalyzeResponse(BaseModel):
    run_id: str
    question: str
    model: str
    status: str
    sql: str
    title: str
    chart_type: str
    reasoning: str
    summary: str
    evidence: list[dict[str, object]]
    columns: list[str]
    rows: list[list[object]]
    trace: list[str]
    warnings: list[str]
    duration_seconds: float
    source: str
    fallback_used: bool


@lru_cache(maxsize=1)
def get_service() -> AnalysisService:
    settings = load_settings()
    client = DeepSeekClient(settings) if settings.model_configured else None
    return AnalysisService(
        DemoDatabase(),
        llm_client=client,
        model=settings.default_model,
        audit_store=AuditStore(settings.audit_db_path),
        source="api-demo",
    )


def require_api_key(x_api_key: Annotated[str | None, Header()] = None) -> None:
    """Enable a lightweight deployment guard when DATAPILOT_API_TOKEN is configured."""
    settings = load_settings()
    expected = os.getenv("DATAPILOT_API_TOKEN")
    if settings.api_token_required and not expected:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="服务要求 API Token，但尚未完成配置。",
        )
    if expected and (not x_api_key or not secrets.compare_digest(x_api_key, expected)):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="缺少或错误的 API Key。",
        )


def validate_model_id(
    model: str | None, default_model: str, allowed_models: tuple[str, ...]
) -> str:
    """Allow only configured DeepSeek model IDs instead of arbitrary upstream targets."""
    selected = model or default_model
    if selected not in allowed_models:
        raise HTTPException(status_code=400, detail="不允许使用未配置的模型。")
    return selected


app = FastAPI(
    title="DataPilot API",
    version="0.2.0",
    description="将自然语言转换为可审计的只读 SQL 分析结果。",
)


@app.get("/healthz")
def healthz() -> dict[str, object]:
    settings = load_settings()
    return {
        "status": "ok",
        "service": "datapilot",
        "model_configured": settings.model_configured,
        "default_model": settings.default_model,
        "api_token_required": settings.api_token_required,
        "allowed_models": list(settings.allowed_models),
    }


@app.post(
    "/v1/analyze",
    response_model=AnalyzeResponse,
    dependencies=[Depends(require_api_key)],
)
def analyze(request: AnalyzeRequest) -> AnalyzeResponse:
    service = get_service()
    settings = load_settings()
    selected_model = validate_model_id(
        request.model, service.model, settings.allowed_models
    )
    if selected_model != service.model:
        service = AnalysisService(
            service.database,
            llm_client=service.llm_client,
            model=selected_model,
            audit_store=service.audit_store,
            source=service.source,
        )
    try:
        result = service.analyze(request.question)
    except (DataAgentError, QueryExecutionError, SQLSafetyError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except Exception as exc:
        logger.exception("unexpected_analysis_error")
        raise HTTPException(status_code=500, detail="分析服务内部错误。") from exc
    return AnalyzeResponse(
        run_id=result.run_id,
        question=result.question,
        model=result.model,
        status=result.status,
        sql=result.executed_sql,
        title=result.title,
        chart_type=result.chart_type,
        reasoning=result.reasoning,
        summary=result.summary,
        evidence=result.evidence,
        columns=result.columns,
        rows=[list(row) for row in result.rows],
        trace=result.trace,
        warnings=result.warnings,
        duration_seconds=result.duration_seconds,
        source=result.source,
        fallback_used=result.fallback_used,
    )


@app.get("/v1/runs", dependencies=[Depends(require_api_key)])
def recent_runs(limit: int = 20) -> dict[str, object]:
    records = get_service().audit_store.recent(limit)  # type: ignore[union-attr]
    return {"items": [record.to_dict() for record in records]}


@app.get("/v1/runs/{run_id}", dependencies=[Depends(require_api_key)])
def get_run(run_id: str) -> dict[str, object]:
    record = get_service().audit_store.get(run_id)  # type: ignore[union-attr]
    if record is None:
        raise HTTPException(status_code=404, detail="找不到对应的运行记录。")
    return record.to_dict()
