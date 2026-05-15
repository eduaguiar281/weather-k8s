"""Portas (Protocols) para desacoplar core de adaptadores de infraestrutura."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Protocol

from langchain_core.messages import BaseMessage

from alert_agent.core.alert_parser import AlertContext


class GrafanaDatasourcePort(Protocol):
    """Subconjunto da API Grafana usado por ContextCollector."""

    async def find_datasource(self, ds_type: str) -> dict | None: ...

    async def query_prometheus_instant(self, expr: str, datasource_uid: str) -> dict: ...

    async def query_loki(
        self,
        log_query: str,
        datasource_uid: str,
        lookback: str | None = None,
        limit: int = 100,
    ) -> dict: ...

    async def get_active_alerts(self) -> list[dict]: ...


class LlmChatPort(Protocol):
    async def invoke(
        self,
        messages: list[BaseMessage],
        *,
        log_extra: dict | None = None,
    ) -> str: ...


class AlertEventPublisher(Protocol):
    async def start(self) -> None: ...

    async def stop(self) -> None: ...

    async def publish_analysis(self, alert: AlertContext, analysis: str) -> None: ...

    async def publish_resolved(self, alert: AlertContext) -> None: ...


SaveAnalysisArtifactFn = Callable[[str], Awaitable[None]]
