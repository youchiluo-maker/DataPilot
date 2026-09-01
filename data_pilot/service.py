from __future__ import annotations

from dataclasses import replace
import logging
import time
from uuid import uuid4

from .agent import AnalysisResult, DataPilotAgent
from .audit import AuditStore, RunRecord, utc_now
from .database import DemoDatabase
from .llm_client import DeepSeekClient


logger = logging.getLogger("datapilot.service")


class AnalysisService:
    """Application service shared by Streamlit, HTTP clients and background jobs."""

    def __init__(
        self,
        database: DemoDatabase,
        *,
        llm_client: DeepSeekClient | None = None,
        model: str = "deepseek-ai/DeepSeek-V4-Pro",
        audit_store: AuditStore | None = None,
        source: str = "demo",
    ) -> None:
        self.database = database
        self.llm_client = llm_client
        self.model = model
        self.audit_store = audit_store
        self.source = source

    def analyze(self, question: str) -> AnalysisResult:
        run_id = uuid4().hex[:12]
        started = utc_now()
        started_perf = time.perf_counter()
        try:
            result = DataPilotAgent(
                database=self.database,
                llm_client=self.llm_client,
                model=self.model,
            ).analyze(question)
            result = replace(
                result,
                run_id=run_id,
                source=self.source,
                status="success",
                fallback_used=result.model == "local-fallback",
            )
            self._record(result, started)
            logger.info(
                "analysis_completed run_id=%s model=%s source=%s rows=%d duration=%.3f fallback=%s",
                run_id,
                result.model,
                self.source,
                len(result.rows),
                result.duration_seconds,
                result.fallback_used,
            )
            return result
        except Exception as exc:
            duration = time.perf_counter() - started_perf
            record = RunRecord(
                run_id=run_id,
                created_at=started,
                question=question.strip(),
                source=self.source,
                model=self.model,
                status="failed",
                duration_seconds=duration,
                row_count=0,
                column_count=0,
                fallback_used=False,
                error=str(exc),
            )
            if self.audit_store is not None:
                self.audit_store.append(record)
            logger.exception("analysis_failed run_id=%s source=%s", run_id, self.source)
            raise

    def _record(self, result: AnalysisResult, created_at: str) -> None:
        if self.audit_store is None:
            return
        self.audit_store.append(
            RunRecord(
                run_id=result.run_id,
                created_at=created_at,
                question=result.question,
                source=result.source,
                model=result.model,
                status=result.status,
                duration_seconds=result.duration_seconds,
                row_count=len(result.rows),
                column_count=len(result.columns),
                fallback_used=result.fallback_used,
                sql=result.executed_sql,
                warnings=tuple(result.warnings),
            )
        )
