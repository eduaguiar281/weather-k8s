"""Testes para RabbitPublisher."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from alert_agent.core.alert_parser import AlertContext
from alert_agent.infra.rabbitmq.publisher import RabbitPublisher


def _alert(**kwargs) -> AlertContext:
    return AlertContext(
        title=kwargs.get("title", "A"),
        state=kwargs.get("state", "firing"),
        message="m",
        labels={"alertname": "A", "severity": "s", "job": "j"},
        annotations={},
        generator_url="",
        fingerprint="fp",
        starts_at="",
        ends_at=kwargs.get("ends_at", ""),
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
        s.rabbitmq_exchange = "ex"
        pub = RabbitPublisher()
        await pub.publish(_alert(), analysis_text="text")
        assert pub._exchange is None


@pytest.mark.asyncio
async def test_publish_no_exchange_logs():
    with patch("alert_agent.infra.rabbitmq.publisher.settings") as s:
        s.rabbitmq_enabled = True
        s.rabbitmq_exchange = "ex"
        s.rabbitmq_analysis_routing_key = "k"
        s.rabbitmq_publish_timeout_seconds = 1.0
        pub = RabbitPublisher()
        pub._exchange = None
        await pub.publish(_alert(), analysis_text="body")


@pytest.mark.asyncio
async def test_publish_analysis_success_path():
    exc = MagicMock()
    exc.publish = AsyncMock()
    with patch("alert_agent.infra.rabbitmq.publisher.settings") as s:
        s.rabbitmq_enabled = True
        s.rabbitmq_exchange = "ex"
        s.rabbitmq_analysis_routing_key = "analysis"
        s.rabbitmq_publish_timeout_seconds = 1.0
        pub = RabbitPublisher()
        pub._exchange = exc
        await pub.publish(_alert(), analysis_text="analysis text")
        exc.publish.assert_awaited()


@pytest.mark.asyncio
async def test_publish_resolved_same_routing_key_as_analysis():
    exc = MagicMock()
    captured = []

    async def capture_publish(msg, routing_key="", **kwargs):
        captured.append({"routing_key": routing_key})

    exc.publish = AsyncMock(side_effect=capture_publish)

    resolved_alert = _alert(state="resolved")
    with patch("alert_agent.infra.rabbitmq.publisher.settings") as s:
        s.rabbitmq_enabled = True
        s.rabbitmq_exchange = "ex"
        s.rabbitmq_analysis_routing_key = "analysis"
        s.rabbitmq_publish_timeout_seconds = 1.0
        pub = RabbitPublisher()
        pub._exchange = exc

        await pub.publish(resolved_alert, analysis_text=None)

    assert captured and captured[0]["routing_key"] == "analysis"
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
        s.rabbitmq_publish_timeout_seconds = 1.0
        pub = RabbitPublisher()
        pub._exchange = exc
        with pytest.raises(DeliveryError):
            await pub.publish(_alert(), analysis_text="x")


@pytest.mark.asyncio
async def test_publish_timeout_reraises():
    exc = MagicMock()
    exc.publish = AsyncMock(side_effect=asyncio.TimeoutError())
    with patch("alert_agent.infra.rabbitmq.publisher.settings") as s:
        s.rabbitmq_enabled = True
        s.rabbitmq_exchange = "ex"
        s.rabbitmq_analysis_routing_key = "analysis"
        s.rabbitmq_publish_timeout_seconds = 1.0
        pub = RabbitPublisher()
        pub._exchange = exc
        with pytest.raises(asyncio.TimeoutError):
            await pub.publish(_alert(), analysis_text="x")


@pytest.mark.asyncio
async def test_start_declares_main_queue_with_single_active_consumer():
    queue_calls: list[tuple[str, dict]] = []

    async def declare_queue_stub(name, durable=True, auto_delete=False, arguments=None):
        qmock = AsyncMock()
        queue_calls.append((name, dict(arguments or {})))
        qmock.bind = AsyncMock()
        return qmock

    ch = AsyncMock()
    ch.declare_exchange = AsyncMock(return_value=MagicMock())
    ch.declare_queue = AsyncMock(side_effect=declare_queue_stub)
    ch.close = AsyncMock()
    ch.is_closed = False

    conn = AsyncMock()
    conn.channel = AsyncMock(return_value=ch)
    conn.is_closed = False
    conn.close = AsyncMock()

    connect = AsyncMock(return_value=conn)

    with patch("alert_agent.infra.rabbitmq.publisher.aio_pika.connect_robust", connect):
        with patch("alert_agent.infra.rabbitmq.publisher.settings") as s:
            s.rabbitmq_enabled = True
            s.rabbitmq_url = "amqp://guest:guest@rabbitmq/"
            s.rabbitmq_exchange = "weather.agent"
            s.rabbitmq_dlx_exchange = "weather.agent.dlx"
            s.rabbitmq_analysis_queue = "weather.agent.analysis"
            s.rabbitmq_analysis_dlq = "weather.agent.analysis.dlq"
            s.rabbitmq_analysis_routing_key = "analysis"
            s.rabbitmq_analysis_single_active_consumer = True
            pub = RabbitPublisher()
            await pub.start()
            await pub.stop()

    main = next(
        (args for args in queue_calls if args[0] == "weather.agent.analysis"),
        None,
    )
    assert main is not None
    _, args_dict = main
    assert args_dict.get("x-dead-letter-exchange") == "weather.agent.dlx"
    assert args_dict.get("x-single-active-consumer") is True


@pytest.mark.asyncio
async def test_start_declares_main_queue_without_sac_when_disabled():
    queue_calls: list[tuple[str, dict]] = []

    async def declare_queue_stub(name, durable=True, auto_delete=False, arguments=None):
        qmock = AsyncMock()
        queue_calls.append((name, dict(arguments or {})))
        qmock.bind = AsyncMock()
        return qmock

    ch = AsyncMock()
    ch.declare_exchange = AsyncMock(return_value=MagicMock())
    ch.declare_queue = AsyncMock(side_effect=declare_queue_stub)
    ch.close = AsyncMock()
    ch.is_closed = False

    conn = AsyncMock()
    conn.channel = AsyncMock(return_value=ch)
    conn.is_closed = False
    conn.close = AsyncMock()

    with patch(
        "alert_agent.infra.rabbitmq.publisher.aio_pika.connect_robust",
        AsyncMock(return_value=conn),
    ):
        with patch("alert_agent.infra.rabbitmq.publisher.settings") as s:
            s.rabbitmq_enabled = True
            s.rabbitmq_url = "amqp://guest:guest@rabbitmq/"
            s.rabbitmq_exchange = "weather.agent"
            s.rabbitmq_dlx_exchange = "weather.agent.dlx"
            s.rabbitmq_analysis_queue = "weather.agent.analysis"
            s.rabbitmq_analysis_dlq = "weather.agent.analysis.dlq"
            s.rabbitmq_analysis_routing_key = "analysis"
            s.rabbitmq_analysis_single_active_consumer = False
            pub = RabbitPublisher()
            await pub.start()
            await pub.stop()

    main = next(
        (args for args in queue_calls if args[0] == "weather.agent.analysis"),
        None,
    )
    assert main is not None
    _, args_dict = main
    assert "x-single-active-consumer" not in args_dict
