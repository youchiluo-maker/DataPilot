from __future__ import annotations

from collections.abc import Iterable
import time

from openai import OpenAI

from .config import Settings


class LLMClientError(RuntimeError):
    """A user-facing model request error."""


class DeepSeekClient:
    """OpenAI-compatible client for SiliconFlow-hosted DeepSeek models."""

    def __init__(self, settings: Settings):
        if not settings.api_key:
            raise LLMClientError("未找到 API Key，请先在项目根目录配置 .env。")
        self._default_model = settings.default_model
        self._timeout = settings.request_timeout_seconds
        self._max_attempts = settings.max_attempts
        self._client = OpenAI(
            api_key=settings.api_key,
            base_url=settings.base_url,
            timeout=self._timeout,
            max_retries=0,
        )

    def chat(
        self,
        messages: Iterable[dict[str, str]],
        model: str | None = None,
        max_tokens: int = 900,
    ) -> str:
        request_messages = list(messages)
        last_error: Exception | None = None
        for attempt in range(1, self._max_attempts + 1):
            try:
                response = self._client.chat.completions.create(
                    model=model or self._default_model,
                    messages=request_messages,
                    max_tokens=max_tokens,
                )
                if not response.choices or not response.choices[0].message.content:
                    raise LLMClientError("模型返回了空内容。")
                return response.choices[0].message.content.strip()
            except LLMClientError:
                raise
            except Exception as exc:
                last_error = exc
                if attempt < self._max_attempts:
                    time.sleep(0.4 * attempt)
        raise LLMClientError(
            f"模型调用失败（已尝试 {self._max_attempts} 次，超时 {self._timeout:.0f}s）：{last_error}"
        ) from last_error
