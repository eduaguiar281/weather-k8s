"""Orquestrador do caso de uso: alerta → contexto → LLM → artefactos / filas."""

from __future__ import annotations

import asyncio
import logging

from langchain_core.messages import HumanMessage, SystemMessage

from alert_agent.config import settings
from alert_agent.core.alert_parser import AlertContext, parse_first_alert
from alert_agent.core.analysis import (
    SYSTEM_PROMPT,
    UserPromptOptions,
    build_user_prompt,
    format_collected_logql_markdown,
    format_collected_promql_markdown,
    parse_label_allowlist_csv,
    truncate_user_prompt_sections,
)
from alert_agent.core.context_collector import ContextCollector
from alert_agent.core.ports import (
    AlertEventPublisher,
    LlmChatPort,
    SaveAnalysisArtifactFn,
)

logger = logging.getLogger(__name__)


def _prompt_options_from_settings(s) -> UserPromptOptions:
    return UserPromptOptions(
        compact_queries=s.llm_prompt_compact_queries,
        max_log_lines_per_category=s.llm_max_log_lines_per_category,
        max_log_line_chars=s.llm_max_log_line_chars,
        label_keys_allowlist=parse_label_allowlist_csv(s.llm_label_keys_allowlist),
    )


class SreAnalysisAgent:
    """
    Agente SRE de análise de alertas:
      1. Interpreta webhook do Grafana
      2. Coleta métricas (Prometheus) e logs (Loki)
      3. Produz análise via LLM
      4. Persistência opcional e publicação em filas (via portas injetadas)
    """

    def __init__(
        self,
        *,
        collector: ContextCollector,
        llm: LlmChatPort,
        publisher: AlertEventPublisher,
        save_analysis_artifact: SaveAnalysisArtifactFn,
    ) -> None:
        self._collector = collector
        self._llm = llm
        self._publisher = publisher
        self._save_analysis_artifact = save_analysis_artifact
        logger.info(
            "SRE analysis agent LLM ready",
            extra={
                "llm_provider": settings.llm_provider,
                "llm_model": settings.llm_model,
            },
        )

    async def start(self) -> None:
        await self._publisher.start()

    async def stop(self) -> None:
        await self._publisher.stop()

    async def analyze_firing_or_pending(self, alert: AlertContext) -> str:
        """Coleta contexto + LLM (não usar para resolved)."""
        metrics, logs, log_queries, related = await self._collect_context(alert)
        analysis = await self._analyze(alert, metrics, logs, log_queries, related)
        await self._save_analysis_artifact(analysis)
        logger.info(
            "Analysis generated",
            extra={"alert_title": alert.title},
        )
        return analysis

    async def handle(self, payload: dict) -> str:
        alert = parse_first_alert(payload)

        if alert is None:
            logger.warning(
                "Webhook received with no valid alerts",
                extra={"event": "webhook_no_valid_alerts"},
            )
            return "Nenhum alerta válido encontrado no payload."

        logger.info(
            "Processing alert",
            extra={"alert_title": alert.title, "alert_state": alert.state},
        )

        if alert.state == "resolved":
            return f"Alerta '{alert.title}' resolvido — nenhuma análise necessária."

        return await self.analyze_firing_or_pending(alert)

    async def handle_and_publish(self, payload: dict) -> None:
        """Processamento em background: todas as mensagens vão para a fila de análise (AMQP)."""
        alert = parse_first_alert(payload)

        if alert is None:
            logger.warning(
                "Webhook received with no valid alerts",
                extra={"event": "webhook_no_valid_alerts"},
            )
            return

        logger.info(
            "Processing alert (background)",
            extra={"alert_title": alert.title, "alert_state": alert.state},
        )

        try:
            if alert.state == "resolved":
                await self._publisher.publish(alert, analysis_text=None)
                return
            if alert.state in ("firing", "pending"):
                analysis = await self.analyze_firing_or_pending(alert)
                await self._publisher.publish(alert, analysis_text=analysis)
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
    ) -> tuple[dict, dict, dict[str, str], list]:
        metrics, logs, related = await asyncio.gather(
            self._collector.collect_metrics(alert),
            self._collector.collect_logs(alert),
            self._collector.collect_related_alerts(alert),
            return_exceptions=True,
        )

        if isinstance(metrics, Exception):
            logger.error(
                "Failed to collect metrics",
                extra={"error": str(metrics)},
            )
            metrics = {}
        log_queries: dict[str, str] = {}
        if isinstance(logs, Exception):
            logger.error(
                "Failed to collect logs",
                extra={"error": str(logs)},
            )
            logs = {}
        else:
            logs, log_queries = logs
        if isinstance(related, Exception):
            logger.error(
                "Failed to fetch related alerts",
                extra={"error": str(related)},
            )
            related = []

        return metrics, logs, log_queries, related

    async def _analyze(
        self,
        alert: AlertContext,
        metrics: dict,
        logs: dict,
        log_queries: dict[str, str],
        related: list,
    ) -> str:
        opts = _prompt_options_from_settings(settings)
        lim = settings.llm_max_user_prompt_chars
        if lim > 0:
            user_prompt, truncated = truncate_user_prompt_sections(
                alert,
                metrics,
                logs,
                related,
                log_queries,
                opts,
                lim,
            )
        else:
            user_prompt = build_user_prompt(
                alert,
                metrics,
                logs,
                related,
                log_queries=log_queries,
                opts=opts,
            )
            truncated = False
        if settings.debug_llm_result:
            logger.debug(
                "LLM user prompt built",
                extra={"chars": len(user_prompt), "truncated": truncated},
            )
        if truncated:
            logger.warning(
                "User prompt truncated for LLM context limit",
                extra={
                    "llm_max_user_prompt_chars": lim,
                    "hint": "Raise LLM_MAX_USER_PROMPT_CHARS or server n_ctx if analysis lacks data.",
                },
            )
        messages = [
            SystemMessage(content=SYSTEM_PROMPT),
            HumanMessage(content=user_prompt),
        ]
        content = await self._llm.invoke(
            messages,
            log_extra={"alert_title": alert.title},
        )
        appendix = format_collected_promql_markdown(metrics)
        appendix += format_collected_logql_markdown(log_queries)
        if appendix:
            content = content.rstrip() + appendix
        return content

    async def chat_test(
        self, user_message: str, system_instruction: str | None = None
    ) -> str:
        """Invoca a LLM com uma mensagem livre (útil para testes)."""
        parts: list = []
        if system_instruction:
            parts.append(SystemMessage(content=system_instruction))
        parts.append(HumanMessage(content=user_message))
        return await self._llm.invoke(parts, log_extra={})
