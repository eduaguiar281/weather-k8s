"""Composition root: instancia adaptadores de infra e o caso de uso em core."""

from __future__ import annotations

from alert_agent.config import settings
from alert_agent.core.context_collector import ContextCollector
from alert_agent.core.sre_analysis_agent import SreAnalysisAgent
from alert_agent.infra.blob.llm_results import save_analysis_markdown_if_enabled
from alert_agent.infra.grafana.client import GrafanaClient
from alert_agent.infra.llm.chat_service import LlmChatService
from alert_agent.infra.llm.factory import build_chat_model
from alert_agent.infra.rabbitmq.publisher import RabbitPublisher


def build_sre_analysis_agent() -> SreAnalysisAgent:
    grafana = GrafanaClient()
    collector = ContextCollector(grafana)
    llm = LlmChatService(build_chat_model(settings))
    publisher = RabbitPublisher()
    return SreAnalysisAgent(
        collector=collector,
        llm=llm,
        publisher=publisher,
        save_analysis_artifact=save_analysis_markdown_if_enabled,
    )
