import logging
from grafana_client import GrafanaClient
from alert_parser import AlertContext

logger = logging.getLogger(__name__)


class ContextCollector:
    """
    Dado um AlertContext, coleta métricas (Prometheus) e logs (Loki)
    relacionados ao serviço/namespace do alerta.
    """

    def __init__(self, client: GrafanaClient):
        self.client = client
        self._prom_uid: str | None = None
        self._loki_uid: str | None = None

    async def _get_prom_uid(self) -> str | None:
        if self._prom_uid is None:
            ds = await self.client.find_datasource("prometheus")
            self._prom_uid = ds["uid"] if ds else None
        return self._prom_uid

    async def _get_loki_uid(self) -> str | None:
        if self._loki_uid is None:
            ds = await self.client.find_datasource("loki")
            self._loki_uid = ds["uid"] if ds else None
        return self._loki_uid

    # ------------------------------------------------------------------
    # Métricas
    # ------------------------------------------------------------------

    async def collect_metrics(self, alert: AlertContext) -> dict:
        uid = await self._get_prom_uid()
        if not uid:
            logger.warning(
                "Prometheus datasource not found",
                extra={"datasource": "prometheus"},
            )
            return {}

        service = alert.service
        ns = alert.namespace
        label_filter = f'job="{service}"' if not ns else f'namespace="{ns}",job="{service}"'

        queries = {
            "cpu_usage": f'rate(process_cpu_seconds_total{{{label_filter}}}[5m])',
            "memory_bytes": f'process_resident_memory_bytes{{{label_filter}}}',
            "http_error_rate": (
                f'sum(rate(http_requests_total{{{label_filter},status=~"5.."}}[5m])) '
                f'/ sum(rate(http_requests_total{{{label_filter}}}[5m]))'
            ),
            "http_latency_p99": (
                f'histogram_quantile(0.99, sum(rate('
                f'http_request_duration_seconds_bucket{{{label_filter}}}[5m])) by (le))'
            ),
            "pod_restarts": f'kube_pod_container_status_restarts_total{{namespace="{ns}"}}' if ns else "",
        }

        results: dict[str, dict] = {}
        for name, expr in queries.items():
            if not expr:
                continue
            try:
                data = await self.client.query_prometheus_instant(expr, uid)
                results[name] = _simplify_prometheus(data)
            except Exception as e:
                logger.warning(
                    "Prometheus query failed",
                    extra={"query_name": name, "error": str(e)},
                )
                results[name] = {"error": str(e)}

        return results

    # ------------------------------------------------------------------
    # Logs
    # ------------------------------------------------------------------

    async def collect_logs(self, alert: AlertContext) -> dict:
        uid = await self._get_loki_uid()
        if not uid:
            logger.warning(
                "Loki datasource not found",
                extra={"datasource": "loki"},
            )
            return {}

        service = alert.service
        ns = alert.namespace

        # monta filtro de labels LogQL
        if ns:
            base_filter = f'{{namespace="{ns}",job="{service}"}}'
        else:
            base_filter = f'{{job="{service}"}}'

        queries = {
            "errors": f'{base_filter} |= "error" | logfmt',
            "exceptions": f'{base_filter} |= "exception" | logfmt',
            "warnings": f'{base_filter} |= "warn" | logfmt',
        }

        results: dict[str, list] = {}
        for name, query in queries.items():
            try:
                data = await self.client.query_loki(query, uid, limit=50)
                results[name] = _simplify_loki(data)
            except Exception as e:
                logger.warning(
                    "Loki query failed",
                    extra={"query_name": name, "error": str(e)},
                )
                results[name] = []

        return results

    # ------------------------------------------------------------------
    # Alertas correlacionados
    # ------------------------------------------------------------------

    async def collect_related_alerts(self, alert: AlertContext) -> list[dict]:
        try:
            all_alerts = await self.client.get_active_alerts()
            service = alert.service
            related = []
            for a in all_alerts:
                lbls = a.get("labels", {})
                if (
                    lbls.get("job") == service
                    or lbls.get("service") == service
                    or lbls.get("namespace") == alert.namespace
                ) and lbls.get("alertname") != alert.title:
                    related.append({
                        "name": lbls.get("alertname"),
                        "severity": lbls.get("severity"),
                        "state": a.get("status", {}).get("state"),
                    })
            return related[:10]
        except Exception as e:
            logger.warning(
                "Failed to fetch related alerts",
                extra={"error": str(e)},
            )
            return []


# ------------------------------------------------------------------
# Simplificadores de resposta
# ------------------------------------------------------------------

def _simplify_prometheus(data: dict) -> dict:
    """Extrai apenas os valores relevantes da resposta Prometheus."""
    try:
        results = data.get("data", {}).get("result", [])
        if not results:
            return {"value": None}
        simplified = []
        for r in results[:5]:           # limita a 5 series
            simplified.append({
                "labels": r.get("metric", {}),
                "value": r.get("value", [None, None])[1],
            })
        return {"series": simplified}
    except Exception:
        return {"raw": str(data)[:500]}


def _simplify_loki(data: dict) -> list[str]:
    """Extrai as últimas linhas de log da resposta Loki."""
    try:
        streams = data.get("data", {}).get("result", [])
        lines: list[str] = []
        for stream in streams:
            for ts, line in stream.get("values", []):
                lines.append(line)
        return lines[:30]               # máximo 30 linhas por categoria
    except Exception:
        return []
