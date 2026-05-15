"""Testes do prompt de análise (contexto enviado à LLM)."""

from __future__ import annotations

import unittest

from alert_agent.core.alert_parser import AlertContext
from alert_agent.core.analysis import (
    UserPromptOptions,
    build_user_prompt,
    parse_label_allowlist_csv,
    truncate_user_prompt_sections,
)


def _minimal_alert(**label_extra: str) -> AlertContext:
    labels: dict[str, str] = {
        "alertname": "TestAlert",
        "severity": "warning",
        "job": "my-service",
        "namespace": "ns1",
    }
    labels.update(label_extra)
    return AlertContext(
        title="TestAlert",
        state="firing",
        message="something wrong",
        labels=labels,
        annotations={},
        generator_url="http://x",
        fingerprint="fp1",
        starts_at="2026-01-01T00:00:00Z",
    )


class BuildUserPromptTests(unittest.TestCase):
    def test_all_metric_values_present(self):
        alert = _minimal_alert()
        metrics = {
            "cpu_usage": {
                "query": "sum(rate(otel_process_cpu_time_seconds_total[5m]))",
                "series": [
                    {"labels": {"pod": "p1", "z_extra": "omit"}, "value": "0.25"},
                ],
            },
            "http_error_rate": {
                "query": "sum(rate(x[5m]))",
                "series": [{"labels": {}, "value": "0.1"}],
            },
        }
        opts = UserPromptOptions()
        text = build_user_prompt(alert, metrics, {}, [], log_queries={}, opts=opts)
        self.assertIn("valor=", text)
        self.assertIn("cpu_usage", text)
        self.assertIn("http_error_rate", text)
        self.assertIn("10,0 %", text)  # humanized error rate

    def test_compact_queries_index_lists_each_metric(self):
        alert = _minimal_alert()
        metrics = {
            "m_a": {"query": "up", "series": [{"labels": {}, "value": "1"}]},
            "m_b": {"query": "down", "error": "fail"},
        }
        log_queries = {"errors": '{service_name="x"} |= ``'}
        opts = UserPromptOptions(compact_queries=True)
        text = build_user_prompt(
            alert,
            metrics,
            {"errors": []},
            [],
            log_queries=log_queries,
            opts=opts,
        )
        self.assertIn("## Queries utilizadas na coleta", text)
        self.assertIn("### PromQL · `m_a`", text)
        self.assertIn("### PromQL · `m_b`", text)
        self.assertIn("### LogQL · `errors`", text)
        self.assertNotIn(
            "```promql\nup\n```",
            text.split("## Métricas coletadas")[1].split("## Logs")[0],
        )

    def test_verbose_mode_repeats_query_under_metric(self):
        alert = _minimal_alert()
        metrics = {
            "cpu_usage": {
                "query": "rate(x[5m])",
                "series": [{"labels": {}, "value": "1"}],
            },
        }
        opts = UserPromptOptions(compact_queries=False)
        text = build_user_prompt(alert, metrics, {}, [], opts=opts)
        self.assertNotIn("## Queries utilizadas na coleta", text)
        self.assertIn("```promql", text)
        self.assertIn("rate(x[5m])", text)

    def test_label_allowlist_omits_unknown_keys_with_count(self):
        alert = _minimal_alert(noise_label="hidden-value")
        allow = parse_label_allowlist_csv("alertname,severity,job,namespace")
        opts = UserPromptOptions(label_keys_allowlist=allow)
        text = build_user_prompt(alert, {}, {}, [], opts=opts)
        self.assertNotIn("hidden-value", text)
        self.assertIn("+1 outros labels omitidos", text)

    def test_truncate_sections_returns_shorter_prompt(self):
        alert = _minimal_alert()
        logs = {"errors": ["line " + str(i) for i in range(400)]}
        metrics = {
            "cpu_usage": {
                "query": "rate(cpu[5m])",
                "series": [{"labels": {}, "value": "0.1"}],
            },
        }
        opts = UserPromptOptions(max_log_lines_per_category=50)
        full = build_user_prompt(alert, metrics, logs, [], opts=opts)
        short, _truncated = truncate_user_prompt_sections(
            alert,
            metrics,
            logs,
            [],
            {},
            opts,
            max_chars=1200,
        )
        self.assertLessEqual(len(short), 1200)
        self.assertLess(len(short), len(full))
        self.assertIn("## Alerta recebido", short)
        self.assertIn("Métricas coletadas", short)


if __name__ == "__main__":
    unittest.main()
