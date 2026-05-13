import logging
from grafana_client import GrafanaClient
from alert_parser import AlertContext

logger = logging.getLogger(__name__)

# Ordem: labels típicos nas métricas OTel / regras Prometheus deste repo primeiro.
_ENV_LABEL_KEYS = ("deployment_environment", "environment", "env", "stage")
_APP_LABEL_KEYS = ("service_name", "app_name", "application", "app")


def _loki_label_esc(value: str) -> str:
    return value.replace("\\", "\\\\").replace('"', '\\"')


def _loki_app_env_base_filter(
    labels: dict[str, str], *, service_fallback: str
) -> str | None:
    """
    Seletor LogQL `{app, env}`: usa os mesmos nomes de label que vêm no alerta
    (ex.: service_name + deployment_environment), para casar com Loki/Promtail/OTel.
    """
    app_key = ""
    app_val = ""
    for key in _APP_LABEL_KEYS:
        raw = labels.get(key)
        if isinstance(raw, str) and raw.strip():
            app_key, app_val = key, raw.strip()
            break
    if not app_val:
        fb = (service_fallback or "").strip()
        if not fb:
            return None
        app_key, app_val = "service_name", fb

    env_key = ""
    env_val = ""
    for key in _ENV_LABEL_KEYS:
        raw = labels.get(key)
        if isinstance(raw, str) and raw.strip():
            env_key, env_val = key, raw.strip()
            break
    if not env_val:
        return None

    e = _loki_label_esc
    return "{" + f'{app_key}="{e(app_val)}", {env_key}="{e(env_val)}"' + "}"


def _promql_env_matcher(labels: dict[str, str]) -> str:
    """Fragmento `,key=\"value\"` para PromQL se os labels do alerta tiverem ambiente."""
    for key in _ENV_LABEL_KEYS:
        raw = labels.get(key)
        if isinstance(raw, str) and raw.strip():
            val = raw.strip().replace("\\", "\\\\").replace('"', '\\"')
            return f',{key}="{val}"'
    return ""


def _otel_http_promql_filter(
    labels: dict[str, str], *, service_fallback: str = ""
) -> str:
    """
    Mesmo filtro que o dashboard Weather — Observabilidade (service_name + ambiente).
    Usa `service_name` do alerta; se faltar, `service_fallback` (ex.: job da app).
    """
    raw_sn = labels.get("service_name")
    if isinstance(raw_sn, str) and raw_sn.strip():
        sn = raw_sn.strip()
    else:
        sn = (service_fallback or "").strip() or "unknown"
    sn_esc = sn.replace("\\", "\\\\").replace('"', '\\"')
    return f'service_name="{sn_esc}"{_promql_env_matcher(labels)}'


def _http_error_and_latency_promql_otel(filter_expr: str) -> tuple[str, str]:
    """PromQL OTel: taxa de erro HTTP (4xx/5xx) e latência p99."""
    http_error_rate = (
        f'sum(rate(otel_http_server_duration_milliseconds_count{{'
        f'{filter_expr},http_status_code=~"4..|5.."}}[5m])) '
        f'/ sum(rate(otel_http_server_duration_milliseconds_count{{'
        f'{filter_expr}}}[5m]))'
    )
    http_latency_p99 = (
        f'histogram_quantile(0.99, sum by (le) (rate('
        f'otel_http_server_duration_milliseconds_bucket{{{filter_expr}}}[5m])))'
    )
    return http_error_rate, http_latency_p99


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

        ns = alert.namespace

        otel_http_f = _otel_http_promql_filter(
            alert.labels, service_fallback=alert.service
        )
        http_error_rate, http_latency_p99 = _http_error_and_latency_promql_otel(
            otel_http_f
        )

        # Métricas de processo vêm do OTel scrape (job Prometheus = otel-collector);
        # filtro igual ao dashboard: service_name + deployment_environment (via alert.labels).
        queries = {
            "cpu_usage": (
                f"sum(rate(otel_process_cpu_time_seconds_total{{{otel_http_f}}}[5m])) "
                f"or sum(rate(otel_process_runtime_cpython_cpu_time_seconds_total{{{otel_http_f}}}[5m]))"
            ),
            "memory_bytes": (
                f"sum(otel_process_memory_usage_bytes{{{otel_http_f}}}) "
                f"or sum(otel_process_runtime_cpython_memory_bytes{{{otel_http_f}}})"
            ),
            "http_error_rate": http_error_rate,
            "http_latency_p99": http_latency_p99,
            "pod_restarts": f'kube_pod_container_status_restarts_total{{namespace="{ns}"}}' if ns else "",
        }

        results: dict[str, dict] = {}
        for name, expr in queries.items():
            if not expr:
                continue
            try:
                data = await self.client.query_prometheus_instant(expr, uid)
                block = _simplify_prometheus(data)
                block["query"] = expr
                results[name] = block
            except Exception as e:
                logger.warning(
                    "Prometheus query failed",
                    extra={"query_name": name, "error": str(e)},
                )
                results[name] = {"query": expr, "error": str(e)}

        return results

    # ------------------------------------------------------------------
    # Logs
    # ------------------------------------------------------------------

    async def collect_logs(
        self, alert: AlertContext
    ) -> tuple[dict[str, list], dict[str, str]]:
        uid = await self._get_loki_uid()
        if not uid:
            logger.warning(
                "Loki datasource not found",
                extra={"datasource": "loki"},
            )
            return {}, {}

        service = alert.service
        ns = alert.namespace

        base_filter = _loki_app_env_base_filter(
            alert.labels, service_fallback=service
        )
        if not base_filter:
            if ns:
                base_filter = (
                    "{"
                    f'namespace="{_loki_label_esc(ns)}",job="{_loki_label_esc(service)}"'
                    "}"
                )
            else:
                base_filter = f'{{job="{_loki_label_esc(service)}"}}'

        queries = {
            "errors": f'{base_filter} |~ "(error|ERROR)"',
            "exceptions": f'{base_filter} |~ "(exception|EXCEPTION|except|EXCEPT)"',
            "warnings": f'{base_filter} |~ "(warning|warn|WARNING|WARN)"',
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

        return results, queries

    # ------------------------------------------------------------------
    # Alertas correlacionados
    # ------------------------------------------------------------------

    async def collect_related_alerts(self, alert: AlertContext) -> list[dict]:
        try:
            all_alerts = await self.client.get_active_alerts()
            service = alert.service
            sn = alert.labels.get("service_name")
            related = []
            for a in all_alerts:
                lbls = a.get("labels", {})
                if (
                    lbls.get("job") == service
                    or lbls.get("service") == service
                    or (sn and lbls.get("service_name") == sn)
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
