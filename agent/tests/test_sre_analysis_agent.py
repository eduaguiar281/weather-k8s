"""Testes para SreAnalysisAgent com dependências falsas."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from alert_agent.core.alert_parser import AlertContext
from alert_agent.core.sre_analysis_agent import SreAnalysisAgent


def _alert(state: str = "firing") -> AlertContext:
    return AlertContext(
        title="MyAlert",
        state=state,
        message="m",
        labels={
            "alertname": "MyAlert",
            "severity": "high",
            "job": "svc",
            "namespace": "ns",
        },
        annotations={},
        generator_url="",
        fingerprint="fp",
        starts_at="2026-01-01T00:00:00Z",
    )


@pytest.fixture
def fake_settings():
    return SimpleNamespace(
        llm_provider="anthropic",
        llm_model="test-model",
        llm_prompt_compact_queries=True,
        llm_max_log_lines_per_category=8,
        llm_max_log_line_chars=220,
        llm_label_keys_allowlist="alertname,severity,job,namespace",
        llm_max_user_prompt_chars=0,
        debug_llm_result=False,
    )


@pytest.fixture
def agent(fake_settings):
    collector = SimpleNamespace(
        collect_metrics=AsyncMock(return_value={}),
        collect_logs=AsyncMock(return_value=({}, {})),
        collect_related_alerts=AsyncMock(return_value=[]),
    )

    async def collect_logs_side(alert):
        return ({"errors": []}, {"errors": '{job="x"}'})

    collector.collect_logs.side_effect = collect_logs_side

    llm = AsyncMock()
    llm.invoke = AsyncMock(return_value="**Análise** ok")

    publisher = SimpleNamespace(
        start=AsyncMock(),
        stop=AsyncMock(),
        publish_analysis=AsyncMock(),
        publish_resolved=AsyncMock(),
    )

    save = AsyncMock()

    with patch("alert_agent.core.sre_analysis_agent.settings", fake_settings):
        yield SreAnalysisAgent(
            collector=collector,
            llm=llm,
            publisher=publisher,
            save_analysis_artifact=save,
        ), collector, llm, publisher, save


@pytest.mark.asyncio
async def test_handle_no_alert(agent):
    ag, *_ = agent
    msg = await ag.handle({"alerts": []})
    assert "Nenhum alerta válido" in msg


@pytest.mark.asyncio
async def test_handle_resolved_skips_llm(agent):
    ag, _, llm, _, save = agent
    msg = await ag.handle(
        {
            "alerts": [
                {
                    "status": "resolved",
                    "labels": {"alertname": "MyAlert"},
                    "annotations": {},
                }
            ]
        }
    )
    assert "resolvido" in msg.lower()
    llm.invoke.assert_not_called()
    save.assert_not_called()


@pytest.mark.asyncio
async def test_handle_firing_runs_llm_and_save(agent):
    ag, coll, llm, _, save = agent
    coll.collect_metrics = AsyncMock(
        return_value={"cpu": {"query": "up", "series": []}}
    )
    coll.collect_logs = AsyncMock(
        side_effect=[({"errors": []}, {"errors": "up"})],
    )
    await ag.handle(
        {
            "status": "firing",
            "alerts": [
                {
                    "status": "firing",
                    "labels": {"alertname": "MyAlert", "job": "j", "namespace": "ns"},
                    "annotations": {"summary": "s"},
                }
            ],
        }
    )
    llm.invoke.assert_awaited()
    save.assert_awaited()


@pytest.mark.asyncio
async def test_handle_and_publish_resolved(agent):
    ag, _, _, pub, _ = agent
    await ag.handle_and_publish(
        {
            "alerts": [
                {
                    "status": "resolved",
                    "labels": {"alertname": "MyAlert", "job": "j"},
                    "annotations": {},
                }
            ],
        }
    )
    pub.publish_resolved.assert_awaited()
    pub.publish_analysis.assert_not_called()


@pytest.mark.asyncio
async def test_handle_and_publish_firing(agent):
    ag, _, _, pub, _ = agent
    await ag.handle_and_publish(
        {
            "alerts": [
                {
                    "status": "firing",
                    "labels": {"alertname": "MyAlert", "job": "j", "namespace": "n"},
                    "annotations": {},
                }
            ],
        }
    )
    pub.publish_analysis.assert_awaited()


@pytest.mark.asyncio
async def test_handle_and_publish_unknown_state(agent):
    ag, _, _, pub, _ = agent
    await ag.handle_and_publish(
        {
            "alerts": [
                {
                    "status": "weird",
                    "labels": {"alertname": "MyAlert", "job": "j"},
                    "annotations": {},
                }
            ],
        }
    )
    pub.publish_analysis.assert_not_called()
    pub.publish_resolved.assert_not_called()


@pytest.mark.asyncio
async def test_collect_context_exception_swallows(agent):
    ag, coll, _, _, _ = agent
    coll.collect_metrics = AsyncMock(side_effect=RuntimeError("e1"))
    coll.collect_logs = AsyncMock(side_effect=RuntimeError("e2"))
    coll.collect_related_alerts = AsyncMock(side_effect=RuntimeError("e3"))

    m, l, lq, r = await ag._collect_context(_alert())
    assert m == {} and l == {} and lq == {} and r == []


@pytest.mark.asyncio
async def test_analyze_appends_promql_markdown(agent, fake_settings):
    ag, coll, llm, _, _ = agent
    fake_settings.llm_max_user_prompt_chars = 0
    coll.collect_metrics = AsyncMock(return_value={})
    metrics = {"m": {"query": "up", "series": [{"labels": {}, "value": "1"}]}}
    coll.collect_logs = AsyncMock(return_value=({}, {"errors": "x"}))
    out = await ag._analyze(_alert(), metrics, {"errors": []}, {"errors": "x"}, [])
    assert "PromQL" in out or "análise" in out.lower()
    llm.invoke.assert_awaited()


@pytest.mark.asyncio
async def test_analyze_with_truncation(fake_settings):
    collector = SimpleNamespace(
        collect_metrics=AsyncMock(return_value={}),
        collect_logs=AsyncMock(return_value=({}, {})),
        collect_related_alerts=AsyncMock(return_value=[]),
    )
    collector.collect_logs = AsyncMock(
        side_effect=[({"e": ["x" * 500]}, {"e": "q"})],
    )
    llm = AsyncMock()
    llm.invoke = AsyncMock(return_value="short")
    publisher = SimpleNamespace(
        start=AsyncMock(),
        stop=AsyncMock(),
        publish_analysis=AsyncMock(),
        publish_resolved=AsyncMock(),
    )
    fake_settings.llm_max_user_prompt_chars = 800
    with patch("alert_agent.core.sre_analysis_agent.settings", fake_settings):
        ag = SreAnalysisAgent(
            collector=collector,
            llm=llm,
            publisher=publisher,
            save_analysis_artifact=AsyncMock(),
        )
        await ag._analyze(
            _alert(),
            {"cpu": {"query": "rate(x[5m])", "series": [{"labels": {}, "value": "1"}]}},
            {"e": ["x" * 500]},
            {"e": "q"},
            [],
        )
    llm.invoke.assert_awaited()
