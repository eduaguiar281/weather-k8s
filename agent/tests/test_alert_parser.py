"""Testes para parse de webhooks e AlertContext."""

from __future__ import annotations

import unittest

from alert_agent.core.alert_parser import AlertContext, parse_first_alert, parse_webhook


class ParseWebhookTests(unittest.TestCase):
    def test_grafana_style_envelope(self):
        payload = {
            "receiver": "alert-agent",
            "status": "firing",
            "alerts": [
                {
                    "status": "firing",
                    "labels": {"alertname": "HighCPU", "job": "api"},
                    "annotations": {
                        "summary": "CPU high",
                        "description": "desc",
                    },
                    "startsAt": "2026-01-01T00:00:00Z",
                    "endsAt": "0001-01-01T00:00:00Z",
                    "generatorURL": "http://g/a",
                    "fingerprint": "fp",
                }
            ],
            "groupLabels": {"alertname": "HighCPU"},
            "commonLabels": {"namespace": "ns1"},
            "commonAnnotations": {"runbook_url": "http://rb"},
            "title": "[FIRING:1] HighCPU",
        }
        ctxs = parse_webhook(payload)
        self.assertEqual(len(ctxs), 1)
        a = ctxs[0]
        self.assertEqual(a.title, "HighCPU")
        self.assertEqual(a.state, "firing")
        self.assertEqual(a.message, "CPU high")
        self.assertEqual(a.labels.get("namespace"), "ns1")
        self.assertEqual(a.labels.get("job"), "api")
        self.assertEqual(a.runbook, "http://rb")
        self.assertEqual(a.fingerprint, "fp")

    def test_common_labels_merged_alert_overrides(self):
        payload = {
            "status": "resolved",
            "commonLabels": {"alertname": "x", "job": "a"},
            "alerts": [{"labels": {"job": "b"}, "annotations": {}, "status": "firing"}],
        }
        a = parse_webhook(payload)[0]
        self.assertEqual(a.labels.get("job"), "b")
        self.assertEqual(a.labels.get("alertname"), "x")

    def test_alert_status_falls_back_to_envelope(self):
        payload = {
            "status": "resolved",
            "alerts": [{"labels": {}, "annotations": {}}],
        }
        self.assertEqual(parse_webhook(payload)[0].state, "resolved")

    def test_non_dict_alerts_skipped(self):
        payload = {"alerts": ["bad", {"labels": {}, "annotations": {}}]}
        self.assertEqual(len(parse_webhook(payload)), 1)

    def test_single_alert_object_without_list(self):
        payload = {
            "labels": {"alertname": "Direct"},
            "annotations": {"message": "hello"},
        }
        ctxs = parse_webhook(payload)
        self.assertEqual(len(ctxs), 1)
        self.assertEqual(ctxs[0].title, "Direct")
        self.assertEqual(ctxs[0].message, "hello")

    def test_parse_first_alert_none_when_empty(self):
        self.assertIsNone(parse_first_alert({"alerts": []}))
        self.assertIsNone(parse_first_alert({"alerts": ["x"]}))

    def test_annotation_message_prefers_summary(self):
        from alert_agent.core.alert_parser import _annotation_message

        self.assertEqual(_annotation_message({"description": "d", "summary": "s"}), "s")


class AlertContextPropertiesTests(unittest.TestCase):
    def test_service_fallback_chain(self):
        a = AlertContext(
            title="t",
            state="f",
            message="",
            labels={"app": "myapp"},
            annotations={},
            generator_url="",
            fingerprint="",
            starts_at="",
        )
        self.assertEqual(a.service, "myapp")

    def test_environment_from_env_label(self):
        a = AlertContext(
            title="t",
            state="f",
            message="",
            labels={"env": "staging"},
            annotations={},
            generator_url="",
            fingerprint="",
            starts_at="",
        )
        self.assertEqual(a.environment, "staging")

    def test_unknown_service(self):
        a = AlertContext(
            title="t",
            state="f",
            message="",
            labels={},
            annotations={},
            generator_url="",
            fingerprint="",
            starts_at="",
        )
        self.assertEqual(a.service, "unknown")


if __name__ == "__main__":
    unittest.main()
