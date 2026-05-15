"""Testes da app FastAPI com agente mockado."""

from __future__ import annotations

import sys
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import httpx
import pytest
from httpx import ASGITransport


@pytest.fixture
def presentation_app_module():
    """Carrega presentation.app com build e blob stubbed (isolado de outros testes)."""
    sys.modules.pop("alert_agent.presentation.app", None)

    fake_agent = SimpleNamespace(
        start=AsyncMock(),
        stop=AsyncMock(),
        handle_and_publish=AsyncMock(),
        chat_test=AsyncMock(return_value="ok"),
    )

    with (
        patch(
            "alert_agent.bootstrap.build_sre_analysis_agent",
            return_value=fake_agent,
        ),
        patch(
            "alert_agent.infra.blob.llm_results.ensure_llm_results_storage_sync",
            lambda: None,
        ),
    ):
        import alert_agent.presentation.app as app_mod

        yield app_mod, fake_agent

    sys.modules.pop("alert_agent.presentation.app", None)


@pytest.mark.asyncio
async def test_health(presentation_app_module):
    app_mod, _ = presentation_app_module
    transport = ASGITransport(app=app_mod.app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as ac:
        r = await ac.get("/health")
    assert r.status_code == 200
    assert r.json().get("status") == "ok"


@pytest.mark.asyncio
async def test_webhook_accepted(presentation_app_module):
    app_mod, fake = presentation_app_module
    transport = ASGITransport(app=app_mod.app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as ac:
        r = await ac.post("/webhook", json={"alerts": [], "receiver": "r"})
    assert r.status_code == 202
    fake.handle_and_publish.assert_called_once()


@pytest.mark.asyncio
async def test_llm_test_ok(presentation_app_module):
    app_mod, fake = presentation_app_module
    transport = ASGITransport(app=app_mod.app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as ac:
        r = await ac.post("/llm/test", json={"message": "hi"})
    assert r.status_code == 200
    assert r.json().get("reply") == "ok"


@pytest.mark.asyncio
async def test_llm_test_connection_error_503(presentation_app_module):
    from openai import APIConnectionError

    app_mod, fake = presentation_app_module
    req = httpx.Request("POST", "http://localhost:9999/v1")
    fake.chat_test = AsyncMock(side_effect=APIConnectionError(request=req, message="x"))
    transport = ASGITransport(app=app_mod.app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as ac:
        r = await ac.post("/llm/test", json={"message": "hi"})
    assert r.status_code == 503


@pytest.mark.asyncio
async def test_list_download_urls_requires_blob(presentation_app_module, monkeypatch):
    app_mod, _ = presentation_app_module
    monkeypatch.setattr(app_mod.settings, "blob_storage", "")
    transport = ASGITransport(app=app_mod.app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as ac:
        r = await ac.get("/llm/download-urls")
    assert r.status_code == 503
