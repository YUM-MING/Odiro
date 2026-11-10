"""LLM 인스턴스 팩토리. 노드마다 temperature/timeout 만 다르게 쓴다."""

from __future__ import annotations

from functools import lru_cache

from odiro.config import settings

LLM_TIMEOUT = 25


@lru_cache(maxsize=8)
def chat(temperature: float = 0.3, model: str | None = None, timeout: int = LLM_TIMEOUT):
    model = model or settings.llm_model
    if settings.llm_provider == "anthropic":
        from langchain_anthropic import ChatAnthropic

        return ChatAnthropic(
            model=model, api_key=settings.anthropic_api_key, temperature=temperature, timeout=timeout, max_retries=1
        )
    from langchain_openai import ChatOpenAI

    return ChatOpenAI(
        model=model, api_key=settings.openai_api_key, temperature=temperature, timeout=timeout, max_retries=1
    )
