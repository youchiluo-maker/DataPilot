from __future__ import annotations

from dataclasses import dataclass
import os

from dotenv import load_dotenv


load_dotenv()


@dataclass(frozen=True)
class Settings:
    api_key: str | None
    base_url: str
    default_model: str
    request_timeout_seconds: float = 60.0
    max_attempts: int = 2
    audit_db_path: str = ".datapilot/audit.db"
    allowed_models: tuple[str, ...] = ()
    api_token_required: bool = False

    @property
    def model_configured(self) -> bool:
        return bool(self.api_key)


def load_settings() -> Settings:
    try:
        timeout = max(5.0, float(os.getenv("DEEPSEEK_TIMEOUT_SECONDS", "60")))
    except ValueError:
        timeout = 60.0
    try:
        attempts = min(3, max(1, int(os.getenv("DEEPSEEK_MAX_ATTEMPTS", "2"))))
    except ValueError:
        attempts = 2
    default_model = os.getenv("DEEPSEEK_MODEL", "deepseek-ai/DeepSeek-V4-Pro")
    configured_models = os.getenv("DATAPILOT_ALLOWED_MODELS", "")
    model_candidates = (
        [item.strip() for item in configured_models.split(",") if item.strip()]
        if configured_models.strip()
        else [
            "deepseek-ai/DeepSeek-V4-Pro",
            "deepseek-ai/DeepSeek-V4-FLASH",
            "deepseek-ai/DeepSeek-R1",
        ]
    )
    allowed_models = tuple(
        dict.fromkeys(
            [
                default_model,
                *model_candidates,
            ]
        )
    )
    require_token = os.getenv("DATAPILOT_REQUIRE_API_TOKEN", "false").lower() in {
        "1",
        "true",
        "yes",
        "on",
    }
    return Settings(
        api_key=os.getenv("DEEPSEEK_API_KEY") or os.getenv("SILICONFLOW_API_KEY"),
        base_url=os.getenv("DEEPSEEK_BASE_URL", "https://api.siliconflow.cn/v1").rstrip("/"),
        default_model=default_model,
        request_timeout_seconds=timeout,
        max_attempts=attempts,
        audit_db_path=os.getenv("DATAPILOT_AUDIT_DB", ".datapilot/audit.db"),
        allowed_models=allowed_models,
        api_token_required=require_token,
    )
