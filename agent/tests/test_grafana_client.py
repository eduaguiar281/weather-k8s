"""Testes para GrafanaClient helpers."""

from __future__ import annotations

import unittest

from alert_agent.infra.grafana.client import _parse_lookback


class ParseLookbackTests(unittest.TestCase):
    def test_minutes(self):
        self.assertEqual(_parse_lookback("15m"), 900)

    def test_hours(self):
        self.assertEqual(_parse_lookback("2H"), 7200)

    def test_days(self):
        self.assertEqual(_parse_lookback("1d"), 86400)

    def test_plain_int(self):
        self.assertEqual(_parse_lookback("120"), 120)


if __name__ == "__main__":
    unittest.main()
