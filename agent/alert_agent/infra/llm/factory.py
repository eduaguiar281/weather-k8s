"""Instancia ChatModel LangChain conforme Settings."""

from __future__ import annotations

from langchain_core.language_models.chat_models import BaseChatModel

from alert_agent.config import Settings


def build_chat_model(s: Settings) -> BaseChatModel:
    provider = s.llm_provider.lower()
    base_url = s.llm_base_url or None
    extra: dict = {}
    if base_url:
        extra["base_url"] = base_url
    mt = s.llm_max_output_tokens
    if mt > 0:
        extra["max_tokens"] = mt

    if provider == "anthropic":
        from langchain_anthropic import ChatAnthropic

        return ChatAnthropic(
            model=s.llm_model,
            api_key=s.llm_api_key,
            **extra,
        )

    if provider == "openai":
        from langchain_openai import ChatOpenAI

        return ChatOpenAI(
            model=s.llm_model,
            api_key=s.llm_api_key,
            **extra,
        )

    raise ValueError(
        f"LLM_PROVIDER '{provider}' não suportado. "
        "Valores aceitos: anthropic, openai"
    )
