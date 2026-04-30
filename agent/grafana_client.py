import time
import httpx
from app.config import settings


class GrafanaClient:
    """Wrapper para a API REST do Grafana."""

    def __init__(self):
        self.base = settings.grafana_url.rstrip("/")
        self.headers = {
            "Authorization": f"Bearer {settings.grafana_token}",
            "Content-Type": "application/json",
        }

    # ------------------------------------------------------------------
    # Datasources
    # ------------------------------------------------------------------

    async def list_datasources(self) -> list[dict]:
        """Retorna todos os datasources configurados no Grafana."""
        async with httpx.AsyncClient() as client:
            r = await client.get(
                f"{self.base}/api/datasources",
                headers=self.headers,
                timeout=10,
            )
            r.raise_for_status()
            return r.json()

    async def find_datasource(self, ds_type: str) -> dict | None:
        """Busca o primeiro datasource do tipo informado (prometheus, loki)."""
        sources = await self.list_datasources()
        for ds in sources:
            if ds.get("type", "").lower() == ds_type.lower():
                return ds
        return None

    # ------------------------------------------------------------------
    # Prometheus
    # ------------------------------------------------------------------

    async def query_prometheus(
        self,
        expr: str,
        datasource_uid: str,
        lookback_seconds: int | None = None,
    ) -> dict:
        """Executa uma query PromQL usando a API de datasource proxy."""
        lb = lookback_seconds or settings.metrics_lookback
        end = int(time.time())
        start = end - lb
        step = max(lb // 60, 15)            # resolução razoável

        async with httpx.AsyncClient() as client:
            r = await client.get(
                f"{self.base}/api/datasources/proxy/uid/{datasource_uid}"
                "/api/v1/query_range",
                headers=self.headers,
                params={
                    "query": expr,
                    "start": start,
                    "end": end,
                    "step": step,
                },
                timeout=30,
            )
            r.raise_for_status()
            return r.json()

    async def query_prometheus_instant(
        self, expr: str, datasource_uid: str
    ) -> dict:
        """Executa uma query PromQL instantânea (valor mais recente)."""
        async with httpx.AsyncClient() as client:
            r = await client.get(
                f"{self.base}/api/datasources/proxy/uid/{datasource_uid}"
                "/api/v1/query",
                headers=self.headers,
                params={"query": expr, "time": int(time.time())},
                timeout=15,
            )
            r.raise_for_status()
            return r.json()

    # ------------------------------------------------------------------
    # Loki
    # ------------------------------------------------------------------

    async def query_loki(
        self,
        log_query: str,
        datasource_uid: str,
        lookback: str | None = None,
        limit: int = 100,
    ) -> dict:
        """Executa uma query LogQL no Loki."""
        lb = lookback or settings.logs_lookback
        end_ns = int(time.time() * 1e9)
        lookback_seconds = _parse_lookback(lb)
        start_ns = int((time.time() - lookback_seconds) * 1e9)

        async with httpx.AsyncClient() as client:
            r = await client.get(
                f"{self.base}/api/datasources/proxy/uid/{datasource_uid}"
                "/loki/api/v1/query_range",
                headers=self.headers,
                params={
                    "query": log_query,
                    "start": start_ns,
                    "end": end_ns,
                    "limit": limit,
                    "direction": "backward",
                },
                timeout=30,
            )
            r.raise_for_status()
            return r.json()

    # ------------------------------------------------------------------
    # Alertas
    # ------------------------------------------------------------------

    async def get_active_alerts(self) -> list[dict]:
        """Retorna todos os alertas ativos no Grafana Alerting."""
        async with httpx.AsyncClient() as client:
            r = await client.get(
                f"{self.base}/api/alertmanager/grafana/api/v2/alerts",
                headers=self.headers,
                params={"active": "true", "silenced": "false"},
                timeout=10,
            )
            r.raise_for_status()
            return r.json()

    # ------------------------------------------------------------------
    # Dashboards
    # ------------------------------------------------------------------

    async def search_dashboards(self, query: str) -> list[dict]:
        """Busca dashboards pelo nome."""
        async with httpx.AsyncClient() as client:
            r = await client.get(
                f"{self.base}/api/search",
                headers=self.headers,
                params={"query": query, "type": "dash-db", "limit": 5},
                timeout=10,
            )
            r.raise_for_status()
            return r.json()


# ------------------------------------------------------------------
# Helpers
# ------------------------------------------------------------------

def _parse_lookback(s: str) -> int:
    """Converte '15m', '1h', '2h' em segundos."""
    s = s.strip().lower()
    if s.endswith("m"):
        return int(s[:-1]) * 60
    if s.endswith("h"):
        return int(s[:-1]) * 3600
    if s.endswith("d"):
        return int(s[:-1]) * 86400
    return int(s)
