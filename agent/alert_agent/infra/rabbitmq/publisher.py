"""
Publicação de análises e eventos resolved no RabbitMQ (AMQP).
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
from datetime import datetime, timezone
import aio_pika
from aio_pika import DeliveryMode, ExchangeType, Message
from aio_pika.exceptions import DeliveryError

from alert_agent.config import settings
from alert_agent.core.alert_parser import AlertContext

logger = logging.getLogger(__name__)


class RabbitPublisher:
    """Declara topologia (exchange, filas, DLX/DLQ) e publica mensagens JSON."""

    def __init__(self) -> None:
        self._connection: aio_pika.RobustConnection | None = None
        self._channel: aio_pika.abc.AbstractChannel | None = None
        self._exchange: aio_pika.abc.AbstractExchange | None = None
        self._started = False

    async def start(self) -> None:
        if not settings.rabbitmq_enabled:
            logger.info(
                "RabbitMQ publisher disabled (RABBITMQ_ENABLED=false)",
                extra={"event": "publisher_disabled", "kind": "startup"},
            )
            return
        if self._started:
            return
        self._connection = await aio_pika.connect_robust(settings.rabbitmq_url)
        self._channel = await self._connection.channel(publisher_confirms=True)
        await self._declare_topology()
        self._started = True
        logger.info(
            "RabbitMQ publisher connected",
            extra={"exchange": settings.rabbitmq_exchange},
        )

    async def stop(self) -> None:
        if self._channel and not self._channel.is_closed:
            await self._channel.close()
        if self._connection and not self._connection.is_closed:
            await self._connection.close()
        self._channel = None
        self._connection = None
        self._exchange = None
        self._started = False

    async def _declare_topology(self) -> None:
        assert self._channel is not None
        ch = self._channel
        s = settings

        dlx = await ch.declare_exchange(
            s.rabbitmq_dlx_exchange,
            ExchangeType.TOPIC,
            durable=True,
        )

        dlq_analysis = await ch.declare_queue(s.rabbitmq_analysis_dlq, durable=True)
        await dlq_analysis.bind(dlx, routing_key=s.rabbitmq_analysis_routing_key)

        dlq_resolved = await ch.declare_queue(s.rabbitmq_resolved_dlq, durable=True)
        await dlq_resolved.bind(dlx, routing_key=s.rabbitmq_resolved_routing_key)

        main_ex = await ch.declare_exchange(
            s.rabbitmq_exchange,
            ExchangeType.TOPIC,
            durable=True,
        )

        q_analysis = await ch.declare_queue(
            s.rabbitmq_analysis_queue,
            durable=True,
            arguments={"x-dead-letter-exchange": s.rabbitmq_dlx_exchange},
        )
        await q_analysis.bind(main_ex, routing_key=s.rabbitmq_analysis_routing_key)

        q_resolved = await ch.declare_queue(
            s.rabbitmq_resolved_queue,
            durable=True,
            arguments={"x-dead-letter-exchange": s.rabbitmq_dlx_exchange},
        )
        await q_resolved.bind(main_ex, routing_key=s.rabbitmq_resolved_routing_key)

        self._exchange = main_ex

    def _alert_headers(self, alert: AlertContext) -> dict[str, str]:
        return {
            "alertname": alert.title,
            "severity": alert.severity,
            "namespace": alert.namespace or "",
        }

    def _log_publish_failure(
        self,
        *,
        event: str,
        kind: str,
        alert: AlertContext,
        routing_key: str,
        error: BaseException,
        analysis: str | None = None,
    ) -> None:
        logger.error(
            "RabbitMQ publish failed",
            extra={
                "event": event,
                "kind": kind,
                "alert_title": alert.title,
                "alert_fingerprint": alert.fingerprint,
                "severity": alert.severity,
                "service": alert.service,
                "namespace": alert.namespace,
                "exchange": settings.rabbitmq_exchange,
                "routing_key": routing_key,
                "error_class": type(error).__name__,
                "error": str(error),
                "analysis_chars": len(analysis) if analysis else 0,
            },
        )

    async def publish_analysis(self, alert: AlertContext, analysis: str) -> None:
        """Publica análise LLM (firing/pending)."""
        kind = "analysis"
        rk = settings.rabbitmq_analysis_routing_key
        if not settings.rabbitmq_enabled:
            logger.info(
                "RabbitMQ publish skipped (disabled)",
                extra={
                    "event": "publisher_disabled",
                    "kind": kind,
                    "alert_title": alert.title,
                    "routing_key": rk,
                },
            )
            return
        if not self._exchange:
            self._log_publish_failure(
                event="publisher_drop",
                kind=kind,
                alert=alert,
                routing_key=rk,
                error=RuntimeError("RabbitMQ exchange not initialized (did start() run?)"),
                analysis=analysis,
            )
            return

        env = os.getenv("ENV", "prod")
        body = {
            "env": env,
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "kind": "analysis",
            "alert": {
                "title": alert.title,
                "state": alert.state,
                "severity": alert.severity,
                "service": alert.service,
                "namespace": alert.namespace,
                "fingerprint": alert.fingerprint,
                "starts_at": alert.starts_at,
                "ends_at": alert.ends_at,
            },
            "analysis": analysis,
        }
        await self._publish_json(
            body=body,
            kind=kind,
            alert=alert,
            routing_key=rk,
            analysis=analysis,
        )

    async def publish_resolved(self, alert: AlertContext) -> None:
        """Publica evento resolved (sem LLM)."""
        kind = "resolved"
        rk = settings.rabbitmq_resolved_routing_key
        if not settings.rabbitmq_enabled:
            logger.info(
                "RabbitMQ publish skipped (disabled)",
                extra={
                    "event": "publisher_disabled",
                    "kind": kind,
                    "alert_title": alert.title,
                    "routing_key": rk,
                },
            )
            return
        if not self._exchange:
            self._log_publish_failure(
                event="publisher_drop",
                kind=kind,
                alert=alert,
                routing_key=rk,
                error=RuntimeError("RabbitMQ exchange not initialized (did start() run?)"),
            )
            return

        env = os.getenv("ENV", "prod")
        body = {
            "env": env,
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "kind": "resolved",
            "alert": {
                "title": alert.title,
                "state": alert.state,
                "severity": alert.severity,
                "service": alert.service,
                "namespace": alert.namespace,
                "fingerprint": alert.fingerprint,
                "starts_at": alert.starts_at,
                "ends_at": alert.ends_at,
            },
        }
        await self._publish_json(
            body=body,
            kind=kind,
            alert=alert,
            routing_key=rk,
            analysis=None,
        )

    async def _publish_json(
        self,
        *,
        body: dict,
        kind: str,
        alert: AlertContext,
        routing_key: str,
        analysis: str | None,
    ) -> None:
        assert self._exchange is not None
        timeout = settings.rabbitmq_publish_timeout_seconds
        raw = json.dumps(body, ensure_ascii=False).encode("utf-8")
        mid = alert.fingerprint or f"{alert.title}:{alert.starts_at}"
        msg = Message(
            raw,
            delivery_mode=DeliveryMode.PERSISTENT,
            content_type="application/json",
            headers=self._alert_headers(alert),
            message_id=mid[:255],
        )
        try:
            await self._exchange.publish(
                msg,
                routing_key=routing_key,
                mandatory=True,
                timeout=timeout,
            )
        except DeliveryError as e:
            self._log_publish_failure(
                event="publisher_unroutable",
                kind=kind,
                alert=alert,
                routing_key=routing_key,
                error=e,
                analysis=analysis,
            )
            raise
        except asyncio.TimeoutError as e:
            self._log_publish_failure(
                event="publisher_timeout",
                kind=kind,
                alert=alert,
                routing_key=routing_key,
                error=e,
                analysis=analysis,
            )
            raise
        except Exception as e:
            self._log_publish_failure(
                event="publisher_drop",
                kind=kind,
                alert=alert,
                routing_key=routing_key,
                error=e,
                analysis=analysis,
            )
            raise
