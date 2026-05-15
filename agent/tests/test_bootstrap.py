"""Cobre o composition root com dependências externas mockadas."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from alert_agent.bootstrap import build_sre_analysis_agent
from alert_agent.core.sre_analysis_agent import SreAnalysisAgent


def test_build_sre_analysis_agent_returns_agent():
    mock_grafana = MagicMock()
    mock_llm_wrapped = MagicMock()

    with (
        patch("alert_agent.bootstrap.GrafanaClient", return_value=mock_grafana),
        patch("alert_agent.bootstrap.ContextCollector") as cc_cls,
        patch("alert_agent.bootstrap.build_chat_model", return_value=MagicMock()),
        patch(
            "alert_agent.bootstrap.LlmChatService",
            return_value=mock_llm_wrapped,
        ),
        patch("alert_agent.bootstrap.RabbitPublisher") as pub_cls,
    ):
        agent = build_sre_analysis_agent()

    assert isinstance(agent, SreAnalysisAgent)
    cc_cls.assert_called_once_with(mock_grafana)
    pub_cls.assert_called_once()
