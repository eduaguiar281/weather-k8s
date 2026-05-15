"""Testes para RabbitPublisher."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from alert_agent.core.alert_parser import AlertContext
from alert_agent.infra.rabbitmq.publisher import RabbitPublisher


def _alert() -> AlertContext:
    return AlertContext(
        title="A",
        state="firing",
        message="m",
        labels={"alertname": "A", "severity": "s", "job": "j"},
        annotations={},
        generator_url="",
        fingerprint="fp",
        starts_at="",
    )


@pytest.mark.asyncio
async def test_start_skipped_when_rabbit_disabled():
    with patch("alert_agent.infra.rabbitmq.publisher.settings") as s:
        s.rabbitmq_enabled = False
        s.rabbitmq_url = "amqp://x"
        pub = RabbitPublisher()
        await pub.start()
        assert pub._connection is None


@pytest.mark.asyncio
async def test_publish_analysis_skipped_when_disabled():
    with patch("alert_agent.infra.rabbitmq.publisher.settings") as s:
        s.rabbitmq_enabled = False
        s.rabbitmq_analysis_routing_key = "a"
        s.rabbitmq_resolved_routing_key = "r"
        s.rabbitmq_exchange = "ex"
        pub = RabbitPublisher()
        await pub.publish_analysis(_alert(), "text")
        assert pub._exchange is None


@pytest.mark.asyncio
async def test_publish_analysis_no_exchange_logs():
    with patch("alert_agent.infra.rabbitmq.publisher.settings") as s:
        s.rabbitmq_enabled = True
        s.rabbitmq_exchange = "ex"
        s.rabbitmq_analysis_routing_key = "k"
        s.rabbitmq_publish_timeout_seconds = 1.0
        s.rabbitmq_resolved_routing_key = "r"
        pub = RabbitPublisher()
        pub._exchange = None
        await pub.publish_analysis(_alert(), "body")


@pytest.mark.asyncio
async def test_publish_analysis_success_path():
    exc = MagicMock()
    exc.publish = AsyncMock()
    with patch("alert_agent.infra.rabbitmq.publisher.settings") as s:
        s.rabbitmq_enabled = True
        s.rabbitmq_exchange = "ex"
        s.rabbitmq_analysis_routing_key = "analysis"
        s.rabbitmq_resolved_routing_key = "resolved"
        s.rabbitmq_publish_timeout_seconds = 1.0
        pub = RabbitPublisher()
        pub._exchange = exc
        await pub.publish_analysis(_alert(), "analysis text")
        exc.publish.assert_awaited()


@pytest.mark.asyncio
async def test_publish_delivery_error_reraises():
    from aio_pika.exceptions import DeliveryError

    exc = MagicMock()
    exc.publish = AsyncMock(side_effect=DeliveryError(None, MagicMock()))
    with patch("alert_agent.infra.rabbitmq.publisher.settings") as s:
        s.rabbitmq_enabled = True
        s.rabbitmq_exchange = "ex"
        s.rabbitmq_analysis_routing_key = "analysis"
        s.rabbitmq_resolved_routing_key = "resolved"
        s.rabbitmq_publish_timeout_seconds = 1.0
        pub = RabbitPublisher()
        pub._exchange = exc
        with pytest.raises(DeliveryError):
            await pub.publish_analysis(_alert(), "x")


@pytest.mark.asyncio
async def test_publish_timeout_reraises():
    exc = MagicMock()
    exc.publish = AsyncMock(side_effect=asyncio.TimeoutError())
    with patch("alert_agent.infra.rabbitmq.publisher.settings") as s:
        s.rabbitmq_enabled = True
        s.rabbitmq_exchange = "ex"
        s.rabbitmq_analysis_routing_key = "analysis"
        s.rabbitmq_resolved_routing_key = "resolved"
        s.rabbitmq_publish_timeout_seconds = 1.0
        pub = RabbitPublisher()
        pub._exchange = exc
        with pytest.raises(asyncio.TimeoutError):
            await pub.publish_analysis(_alert(), "x")
