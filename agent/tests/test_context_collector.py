"""Testes para ContextCollector e simplificadores."""

from __future__ import annotations

import unittest

import pytest

from alert_agent.core.alert_parser import AlertContext
from alert_agent.core.context_collector import (
    ContextCollector,
    _simplify_loki,
    _simplify_prometheus,
)


def _sample_alert() -> AlertContext:
    return AlertContext(
        title="T",
        state="firing",
        message="m",
        labels={
            "alertname": "T",
            "severity": "warn",
            "service_name": "svc",
            "deployment_environment": "prod",
            "namespace": "ns1",
            "job": "svc",
        },
        annotations={},
        generator_url="",
        fingerprint="fp",
        starts_at="2026-01-01T00:00:00Z",
    )


class SimplifyTests(unittest.TestCase):
    def test_prometheus_empty_result(self):
        self.assertEqual(
            _simplify_prometheus({"data": {"result": []}}), {"value": None}
        )

    def test_prometheus_malformed(self):
        out = _simplify_prometheus({"data": None})
        self.assertIn("raw", out)

    def test_loki_streams(self):
        data = {
            "data": {
                "result": [
                    {"values": [["1", "line a"], ["2", "line b"]]},
                ]
            }
        }
        lines = _simplify_loki(data)
        self.assertIn("line a", lines)

    def test_loki_malformed(self):
        self.assertEqual(_simplify_loki({}), [])


class FakeGrafanaNoDs:
    async def find_datasource(self, ds_type: str) -> dict | None:
        return None

    async def query_prometheus_instant(self, expr: str, datasource_uid: str) -> dict:
        raise AssertionError("should not be called")

    async def query_loki(
        self,
        log_query: str,
        datasource_uid: str,
        lookback: str | None = None,
        limit: int = 100,
    ) -> dict:
        raise AssertionError("should not be called")

    async def get_active_alerts(self) -> list[dict]:
        return []


class FakeGrafanaFull:
    def __init__(self) -> None:
        self.prom_calls: list[str] = []
        self.loki_calls: list[str] = []

    async def find_datasource(self, ds_type: str) -> dict | None:
        return {"uid": ds_type[0] + "-uid", "type": ds_type}

    async def query_prometheus_instant(self, expr: str, datasource_uid: str) -> dict:
        self.prom_calls.append(expr)
        if "fail_query" in expr:
            raise RuntimeError("boom")
        return {"data": {"result": [{"metric": {"pod": "p1"}, "value": [0, "1"]}]}}

    async def query_loki(
        self,
        log_query: str,
        datasource_uid: str,
        lookback: str | None = None,
        limit: int = 100,
    ) -> dict:
        self.loki_calls.append(log_query)
        if "FAIL" in log_query:
            raise RuntimeError("loki err")
        return {
            "data": {
                "result": [
                    {"values": [["1", "error stacktrace"]]},
                ]
            },
        }

    async def get_active_alerts(self) -> list[dict]:
        return [
            {
                "status": {"state": "firing"},
                "labels": {
                    "alertname": "OtherAlert",
                    "severity": "warning",
                    "job": "svc",
                    "namespace": "ns1",
                },
            },
            {
                "status": {"state": "firing"},
                "labels": {"alertname": "T", "job": "svc"},
            },
        ]


@pytest.mark.asyncio
async def test_collect_metrics_no_prometheus():
    c = ContextCollector(FakeGrafanaNoDs())
    out = await c.collect_metrics(_sample_alert())
    assert out == {}


@pytest.mark.asyncio
async def test_collect_logs_no_loki():
    c = ContextCollector(FakeGrafanaNoDs())
    logs, queries = await c.collect_logs(_sample_alert())
    assert logs == {} and queries == {}


@pytest.mark.asyncio
async def test_collect_metrics_and_logs_happy_path():
    fake = FakeGrafanaFull()
    c = ContextCollector(fake)
    metrics = await c.collect_metrics(_sample_alert())
    assert "cpu_usage" in metrics
    assert "query" in metrics["cpu_usage"]
    logs, qmap = await c.collect_logs(_sample_alert())
    assert "errors" in logs
    assert "errors" in qmap
    related = await c.collect_related_alerts(_sample_alert())
    assert any(r.get("name") == "OtherAlert" for r in related)


@pytest.mark.asyncio
async def test_collect_metrics_handles_query_exception():
    class F(FakeGrafanaFull):
        async def query_prometheus_instant(self, expr, uid):
            if 'http_status_code=~"4..|5.."' in expr:
                raise RuntimeError("prom down")
            return await super().query_prometheus_instant(expr, uid)

    c = ContextCollector(F())
    metrics = await c.collect_metrics(_sample_alert())
    assert "http_error_rate" in metrics
    assert "error" in metrics["http_error_rate"]


@pytest.mark.asyncio
async def test_collect_logs_handles_exception():
    class F(FakeGrafanaFull):
        async def query_loki(self, q, uid, lookback=None, limit=100):
            if "EXCEPTION" in q:
                raise RuntimeError("x")
            return await super().query_loki(q, uid, lookback=lookback, limit=limit)

    c = ContextCollector(F())
    logs, _ = await c.collect_logs(_sample_alert())
    assert logs.get("exceptions") == []


@pytest.mark.asyncio
async def test_collect_related_alerts_exception_returns_empty():
    class F(FakeGrafanaFull):
        async def get_active_alerts(self):
            raise RuntimeError("no")

    c = ContextCollector(F())
    assert await c.collect_related_alerts(_sample_alert()) == []


@pytest.mark.asyncio
async def test_collect_logs_fallback_namespace_only():
    alert = AlertContext(
        title="T",
        state="firing",
        message="m",
        labels={
            "alertname": "T",
            "severity": "w",
            "job": "onlyjob",
            "namespace": "nsx",
        },
        annotations={},
        generator_url="",
        fingerprint="f",
        starts_at="",
    )
    fake = FakeGrafanaFull()
    c = ContextCollector(fake)
    _, qmap = await c.collect_logs(alert)
    assert any("namespace=" in q for q in qmap.values())
