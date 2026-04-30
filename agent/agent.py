import logging
import anthropic

from app.config import settings
from app.tools.grafana_client import GrafanaClient
from app.tools.alert_parser import parse_webhook, AlertContext
from app.tools.context_collector import ContextCollector
from app.prompts.analysis import SYSTEM_PROMPT, build_user_prompt

logger = logging.getLogger(__name__)


class AlertAgent:
    """
    Orquestra o fluxo completo:
      1. Parseia o webhook do Grafana
      2. Coleta métricas (Prometheus) e logs (Loki)
      3. Envia para a Claude API
      4. Retorna a análise formatada
    """

    def __init__(self):
        self.grafana = GrafanaClient()
        self.collector = ContextCollector(self.grafana)
        self.claude = anthropic.AsyncAnthropic(
            api_key=settings.anthropic_api_key
        )

    async def handle(self, payload: dict) -> str:
        alerts = parse_webhook(payload)

        if not alerts:
            logger.warning("Webhook recebido sem alertas válidos.")
            return "Nenhum alerta válido encontrado no payload."

        # processa o primeiro alerta (pode ser expandido para múltiplos)
        alert = alerts[0]
        logger.info(f"Processando alerta: {alert.title} [{alert.state}]")

        if alert.state == "resolved":
            return f"Alerta '{alert.title}' resolvido — nenhuma análise necessária."

        # coleta contexto em paralelo
        metrics, logs, related = await self._collect_context(alert)

        # gera análise com Claude
        analysis = await self._analyze(alert, metrics, logs, related)

        logger.info(f"Análise gerada para: {alert.title}")
        return analysis

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

        # se alguma coleta falhar, substitui por vazio
        if isinstance(metrics, Exception):
            logger.error(f"Falha ao coletar métricas: {metrics}")
            metrics = {}
        if isinstance(logs, Exception):
            logger.error(f"Falha ao coletar logs: {logs}")
            logs = {}
        if isinstance(related, Exception):
            logger.error(f"Falha ao buscar alertas relacionados: {related}")
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

        message = await self.claude.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=1500,
            system=SYSTEM_PROMPT,
            messages=[{"role": "user", "content": user_prompt}],
        )

        return message.content[0].text
