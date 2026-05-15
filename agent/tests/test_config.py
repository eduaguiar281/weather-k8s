"""Testes de configuração e reescrita de URL."""

from __future__ import annotations

import socket
import unittest
from unittest.mock import patch

from pydantic_settings import SettingsConfigDict

from alert_agent.config import (
    Settings,
    _rewrite_host_docker_internal_if_dns_fails,
)


class RewriteHostTests(unittest.TestCase):
    def test_non_docker_url_unchanged(self):
        self.assertEqual(
            _rewrite_host_docker_internal_if_dns_fails("http://localhost:3000"),
            "http://localhost:3000",
        )

    @patch.object(socket, "getaddrinfo", side_effect=socket.gaierror("nx"))
    def test_docker_host_rewritten_on_dns_fail(self, _):
        u = "http://host.docker.internal:9999/path"
        out = _rewrite_host_docker_internal_if_dns_fails(u)
        self.assertIn("127.0.0.1", out)
        self.assertIn("9999", out)


class SettingsEnvFileTests(unittest.TestCase):
    def test_settings_without_env_file(self):
        class S(Settings):
            model_config = SettingsConfigDict(
                env_file=None,
                env_file_encoding="utf-8",
                extra="ignore",
            )

        s = S(grafana_url="http://example.test")
        self.assertEqual(s.grafana_url, "http://example.test")


if __name__ == "__main__":
    unittest.main()
