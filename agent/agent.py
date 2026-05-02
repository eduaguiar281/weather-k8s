import logging
from langchain_core.messages import SystemMessage, HumanMessage
from langchain_core.language_models.chat_models import BaseChatModel

from config import settings
from grafana_client import GrafanaClient
from alert_parser import parse_webhook, AlertContext
from context_collector import ContextCollector
from analysis import SYSTEM_PROMPT, build_user_prompt
from rabbit_publisher import RabbitPublisher

logger = logging.getLogger(__name__)


def _build_llm(s) -> BaseChatModel:
    """Instancia o modelo de LLM de acordo com LLM_PROVIDER."""
    provider = s.llm_provider.lower()
    base_url = s.llm_base_url or None

    if provider == "anthropic":
        from langchain_anthropic import ChatAnthropic
        return ChatAnthropic(
            model=s.llm_model,
            api_key=s.llm_api_key,
            **({"base_url": base_url} if base_url else {}),
        )

    if provider == "openai":
        from langchain_openai import ChatOpenAI
        return ChatOpenAI(
            model=s.llm_model,
            api_key=s.llm_api_key,
            **({"base_url": base_url} if base_url else {}),
        )

    raise ValueError(
        f"LLM_PROVIDER '{provider}' não suportado. "
        "Valores aceitos: anthropic, openai"
    )


class AlertAgent:
    """
    Orquestra o fluxo completo:
      1. Parseia o webhook do Grafana
      2. Coleta métricas (Prometheus) e logs (Loki)
      3. Envia para a LLM via LangChain
      4. Retorna a análise formatada
    """

    def __init__(self):
        self.grafana = GrafanaClient()
        self.collector = ContextCollector(self.grafana)
        self.llm = _build_llm(settings)
        self._rabbit = RabbitPublisher()
        logger.info(
            "Alert agent LLM started",
            extra={
                "llm_provider": settings.llm_provider,
                "llm_model": settings.llm_model,
            },
        )

    async def start(self) -> None:
        await self._rabbit.start()

    async def stop(self) -> None:
        await self._rabbit.stop()

    async def analyze_firing_or_pending(self, alert: AlertContext) -> str:
        """Coleta contexto + LLM (não usar para resolved)."""
        metrics, logs, related = await self._collect_context(alert)
        analysis = await self._analyze(alert, metrics, logs, related)
        logger.info(
            "Analysis generated",
            extra={"alert_title": alert.title},
        )
        return analysis

    async def handle(self, payload: dict) -> str:
        alerts = parse_webhook(payload)

        if not alerts:
            logger.warning(
                "Webhook received with no valid alerts",
                extra={"event": "webhook_no_valid_alerts"},
            )
            return "Nenhum alerta válido encontrado no payload."

        alert = alerts[0]
        logger.info(
            "Processing alert",
            extra={"alert_title": alert.title, "alert_state": alert.state},
        )

        if alert.state == "resolved":
            return f"Alerta '{alert.title}' resolvido — nenhuma análise necessária."

        return await self.analyze_firing_or_pending(alert)

    async def handle_and_publish(self, payload: dict) -> None:
        """Processamento em background: publica em analysis ou resolved no RabbitMQ."""
        alerts = parse_webhook(payload)

        if not alerts:
            logger.warning(
                "Webhook received with no valid alerts",
                extra={"event": "webhook_no_valid_alerts"},
            )
            return

        alert = alerts[0]
        logger.info(
            "Processing alert (background)",
            extra={"alert_title": alert.title, "alert_state": alert.state},
        )

        try:
            if alert.state == "resolved":
                await self._rabbit.publish_resolved(alert)
                return
            if alert.state in ("firing", "pending"):
                analysis = await self.analyze_firing_or_pending(alert)
                await self._rabbit.publish_analysis(alert, analysis)
                return
            logger.warning(
                "Unknown alert state, skipping RabbitMQ publish",
                extra={"alert_title": alert.title, "alert_state": alert.state},
            )
        except Exception as e:
            logger.error(
                "Background handle_and_publish failed",
                extra={
                    "alert_title": alert.title,
                    "alert_state": alert.state,
                    "error": str(e),
                    "error_class": type(e).__name__,
                },
            )

    async def _collect_context(
        self, alert: AlertContext
    ) -> tuple[dict, dict, list]:
        import asyncio
        metrics, logs, related = await asyncio.gather(
            self.collector.collect_metrics(alert),
            self.collector.collect_logs(alert),
            self.collector.collect_related_alerts(alert),
            return_exceptions=True,
        )

        if isinstance(metrics, Exception):
            logger.error(
                "Failed to collect metrics",
                extra={"error": str(metrics)},
            )
            metrics = {}
        if isinstance(logs, Exception):
            logger.error(
                "Failed to collect logs",
                extra={"error": str(logs)},
            )
            logs = {}
        if isinstance(related, Exception):
            logger.error(
                "Failed to fetch related alerts",
                extra={"error": str(related)},
            )
            related = []

        return metrics, logs, related

    async def _analyze(
        self,
        alert: AlertContext,
        metrics: dict,
        logs: dict,
        related: list,
    ) -> str:
        user_prompt = build_user_prompt(alert, metrics, logs, related)
        messages = [
            SystemMessage(content=SYSTEM_PROMPT),
            HumanMessage(content=user_prompt),
        ]
        response = await self.llm.ainvoke(messages)
        return response.content
