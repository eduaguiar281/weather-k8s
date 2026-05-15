"""Ramos extra de analysis.py (humanize, anexos, truncagem)."""

from __future__ import annotations

import unittest

from alert_agent.core.alert_parser import AlertContext
from alert_agent.core.analysis import (
    UserPromptOptions,
    _humanize_prometheus_value,
    build_user_prompt,
    format_collected_logql_markdown,
    format_collected_promql_markdown,
    parse_label_allowlist_csv,
    truncate_user_prompt,
)


def _alert(**kwargs) -> AlertContext:
    labels = {
        "alertname": "A",
        "severity": "warn",
        "job": "j",
        "namespace": "ns",
    }
    labels.update(kwargs.pop("labels", {}))
    annotations = kwargs.pop("annotations", {})
    return AlertContext(
        title=kwargs.pop("title", "A"),
        state=kwargs.pop("state", "firing"),
        message=kwargs.pop("message", "m"),
        labels=labels,
        annotations=annotations,
        generator_url=kwargs.pop("generator_url", ""),
        fingerprint=kwargs.pop("fingerprint", "f"),
        starts_at=kwargs.pop("starts_at", "2026-01-01T00:00:00Z"),
        ends_at=kwargs.pop("ends_at", ""),
    )


class HumanizePrometheusTests(unittest.TestCase):
    def test_none_raw(self):
        self.assertIsNone(_humanize_prometheus_value("x", None, None))

    def test_http_latency_ms_query(self):
        self.assertIn(
            "ms",
            _humanize_prometheus_value(
                "http_latency_p99",
                1.5,
                "otel_http_server_duration_milliseconds_bucket{}",
            )
            or "",
        )

    def test_http_latency_seconds_query(self):
        self.assertIn(
            "1500",
            _humanize_prometheus_value("http_latency_p99", 1.5, "some_seconds_bucket")
            or "",
        )

    def test_memory_gib(self):
        v = (1024**3) * 2.5
        h = _humanize_prometheus_value("memory_bytes", v, None)
        self.assertIn("GiB", h or "")

    def test_memory_mib(self):
        h = _humanize_prometheus_value("memory_bytes", 100 * 1024 * 1024, None)
        self.assertIn("MiB", h or "")

    def test_cpu_usage(self):
        h = _humanize_prometheus_value("cpu_usage", 0.5, "rate(x[5m])")
        self.assertIn("núcleo", h or "")


class FormatMarkdownTests(unittest.TestCase):
    def test_promql_empty(self):
        self.assertEqual(format_collected_promql_markdown({}), "")

    def test_logql_nonempty(self):
        s = format_collected_logql_markdown({"e": '{job="x"} |= ``'})
        self.assertIn("LogQL", s)
        self.assertIn("`e`", s)


class TruncateUserPromptTests(unittest.TestCase):
    def test_no_truncation_when_within_budget(self):
        t, cut = truncate_user_prompt("short", 100)
        self.assertFalse(cut)
        self.assertEqual(t, "short")

    def test_truncation_adds_notice(self):
        long = "a" * 2000
        t, cut = truncate_user_prompt(long, 400)
        self.assertTrue(cut)
        self.assertLessEqual(len(t), 400)
        self.assertIn("truncado", t.lower())


class BuildUserPromptBranchTests(unittest.TestCase):
    def test_ends_at_and_runbook_in_header(self):
        alert = _alert(
            annotations={"runbook_url": "http://rb", "summary": "s"},
            ends_at="2026-01-02T00:00:00Z",
        )
        text = build_user_prompt(alert, {}, {}, [], opts=UserPromptOptions())
        self.assertIn("Encerra em", text)
        self.assertIn("http://rb", text)

    def test_related_alerts_section(self):
        alert = _alert()
        text = build_user_prompt(
            alert,
            {},
            {},
            [{"name": "Other", "severity": "crit", "state": "firing"}],
            opts=UserPromptOptions(),
        )
        self.assertIn("Other", text)
        self.assertIn("correlacionados", text)

    def test_metric_series_none_value(self):
        alert = _alert()
        text = build_user_prompt(
            alert,
            {"m": {"query": "up", "series": [{"labels": {}, "value": None}]}},
            {},
            [],
            opts=UserPromptOptions(),
        )
        self.assertIn("m", text)

    def test_default_allowlist_when_csv_empty(self):
        self.assertTrue("job" in parse_label_allowlist_csv(""))


if __name__ == "__main__":
    unittest.main()
