"""Testes para factory LangChain e LlmChatService."""

from __future__ import annotations

import unittest
from unittest.mock import AsyncMock, patch

import pytest

from alert_agent.config import Settings
from alert_agent.infra.llm.chat_service import LlmChatService
from alert_agent.infra.llm.factory import build_chat_model
from pydantic_settings import SettingsConfigDict


class SettingsForFactoryTests(Settings):
    model_config = SettingsConfigDict(env_file=None, extra="ignore")


class SimpleContent:
    def __init__(self, content, usage) -> None:
        self.content = content
        self.usage_metadata = usage


class BuildChatModelTests(unittest.TestCase):
    def test_invalid_provider(self):
        s = SettingsForFactoryTests(llm_provider="unknown")
        with self.assertRaises(ValueError):
            build_chat_model(s)

    def test_anthropic_build(self):
        s = SettingsForFactoryTests(
            llm_provider="anthropic", llm_model="m", llm_api_key="k"
        )
        with patch("langchain_anthropic.ChatAnthropic") as m:
            build_chat_model(s)
            m.assert_called_once()

    def test_openai_build(self):
        s = SettingsForFactoryTests(
            llm_provider="openai", llm_model="m", llm_api_key="k"
        )
        with patch("langchain_openai.ChatOpenAI") as m:
            build_chat_model(s)
            m.assert_called_once()

    def test_max_tokens_passed_when_positive(self):
        s = SettingsForFactoryTests(
            llm_provider="openai",
            llm_model="m",
            llm_api_key="k",
            llm_max_output_tokens=512,
        )
        with patch("langchain_openai.ChatOpenAI") as m:
            build_chat_model(s)
            _, kwargs = m.call_args
            assert kwargs.get("max_tokens") == 512


@pytest.mark.asyncio
async def test_llm_chat_service_string_content():
    model = AsyncMock()
    model.ainvoke = AsyncMock(
        return_value=SimpleContent("hello", {"input_tokens": 1, "output_tokens": 2})
    )
    svc = LlmChatService(model)
    out = await svc.invoke([], log_extra={})
    assert out == "hello"
    model.ainvoke.assert_awaited_once()


@pytest.mark.asyncio
async def test_llm_chat_service_list_content():
    model = AsyncMock()
    model.ainvoke = AsyncMock(return_value=SimpleContent([{"text": "z"}], None))
    svc = LlmChatService(model)
    out = await svc.invoke([], log_extra={})
    assert "z" in out
