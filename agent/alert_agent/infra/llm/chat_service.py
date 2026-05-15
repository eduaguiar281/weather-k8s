"""Serviço fino de invocação LLM com logging de tokens (DRY)."""

from __future__ import annotations

import logging

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import BaseMessage

from alert_agent.infra.llm.usage import extract_llm_usage_tokens

logger = logging.getLogger(__name__)


class LlmChatService:
    """Envolve BaseChatModel com logging uniforme de usage."""

    def __init__(self, model: BaseChatModel) -> None:
        self._model = model

    async def invoke(
        self,
        messages: list[BaseMessage],
        *,
        log_extra: dict | None = None,
    ) -> str:
        response = await self._model.ainvoke(messages)
        in_tok, out_tok = extract_llm_usage_tokens(response)
        extra = dict(log_extra or {})
        extra["llm_input_tokens"] = in_tok
        extra["llm_output_tokens"] = out_tok
        logger.info(
            "LLM tokens: entrada=%s saída=%s",
            in_tok if in_tok is not None else "n/d",
            out_tok if out_tok is not None else "n/d",
            extra=extra,
        )
        content = response.content
        if isinstance(content, str):
            return content
        return str(content)
