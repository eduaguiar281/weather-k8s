from __future__ import annotations

from dataclasses import dataclass, field


def _merge_str_maps(common: dict | None, overlay: dict | None) -> dict[str, str]:
    """Mescla maps do envelope Alertmanager (*Common*) com os do alerta (overlay vence)."""
    out: dict[str, str] = {}
    base = common or {}
    for k, v in base.items():
        if v is not None:
            out[str(k)] = v if isinstance(v, str) else str(v)
    for k, v in (overlay or {}).items():
        if v is not None:
            out[str(k)] = v if isinstance(v, str) else str(v)
    return out


def _annotation_message(annotations: dict[str, str]) -> str:
    """Prometheus costuma usar summary + description; Grafana às vezes usa message."""
    for key in ("summary", "description", "message"):
        raw = annotations.get(key)
        if isinstance(raw, str) and raw.strip():
            return raw.strip()
    return ""


@dataclass
class AlertContext:
    """Alerta normalizado (webhook Grafana Alerting e/ou Prometheus Alertmanager)."""

    title: str
    state: str  # firing | resolved | pending
    message: str
    labels: dict[str, str]
    annotations: dict[str, str]
    generator_url: str
    fingerprint: str
    starts_at: str
    ends_at: str = ""
    raw: dict = field(default_factory=dict)

    # campos extraídos dos labels para facilitar o uso
    @property
    def service(self) -> str:
        return (
            self.labels.get("job")
            or self.labels.get("service")
            or self.labels.get("app")
            or "unknown"
        )

    @property
    def namespace(self) -> str:
        return self.labels.get("namespace", "")

    @property
    def environment(self) -> str:
        """Ambiente lógico (dev/staging/prod) a partir de labels comuns do Alertmanager/K8s."""
        for key in ("deployment_environment", "environment", "env", "stage"):
            raw = self.labels.get(key)
            if isinstance(raw, str) and raw.strip():
                return raw.strip()
        return ""

    @property
    def severity(self) -> str:
        return self.labels.get("severity", "unknown")

    @property
    def runbook(self) -> str:
        return self.annotations.get("runbook_url", "")


def parse_webhook(payload: dict) -> list[AlertContext]:
    """
    Converte o payload de webhook em AlertContext.

    Compatível com o formato do Prometheus Alertmanager (receiver, alerts,
    commonLabels, commonAnnotations, status no envelope — ver alertmanager.yml)
    e com o envelope do Grafana Alerting (ex.: campo title).
    """
    alerts_raw = payload.get("alerts")
    if not isinstance(alerts_raw, list):
        alerts_raw = [payload]

    envelope_status = payload.get("status")
    notify_status = (
        envelope_status.lower().strip()
        if isinstance(envelope_status, str) and envelope_status.strip()
        else ""
    )

    common_labels = (
        payload.get("commonLabels")
        if isinstance(payload.get("commonLabels"), dict)
        else {}
    )
    common_annotations = (
        payload.get("commonAnnotations")
        if isinstance(payload.get("commonAnnotations"), dict)
        else {}
    )
    group_labels = (
        payload.get("groupLabels")
        if isinstance(payload.get("groupLabels"), dict)
        else {}
    )

    fallback_title = (
        payload.get("title")
        or group_labels.get("alertname")
        or common_labels.get("alertname")
        or "Alerta sem título"
    )

    contexts: list[AlertContext] = []

    for alert in alerts_raw:
        if not isinstance(alert, dict):
            continue

        labels = _merge_str_maps(
            common_labels,
            alert.get("labels") if isinstance(alert.get("labels"), dict) else {},
        )
        annotations = _merge_str_maps(
            common_annotations,
            (
                alert.get("annotations")
                if isinstance(alert.get("annotations"), dict)
                else {}
            ),
        )

        raw_status = alert.get("status")
        if isinstance(raw_status, str) and raw_status.strip():
            norm_state = raw_status.lower().strip()
        elif notify_status:
            norm_state = notify_status
        else:
            norm_state = "firing"

        title = labels.get("alertname") or fallback_title

        starts = alert.get("startsAt")
        starts_at = (
            starts
            if isinstance(starts, str)
            else (str(starts) if starts is not None else "")
        )
        ends = alert.get("endsAt")
        ends_at = (
            ends if isinstance(ends, str) else (str(ends) if ends is not None else "")
        )

        gen = alert.get("generatorURL") or alert.get("generator_url")
        generator_url = (
            gen if isinstance(gen, str) else (str(gen) if gen is not None else "")
        )

        contexts.append(
            AlertContext(
                title=title,
                state=norm_state,
                message=_annotation_message(annotations),
                labels=labels,
                annotations=annotations,
                generator_url=generator_url,
                fingerprint=str(alert.get("fingerprint", "") or ""),
                starts_at=starts_at,
                ends_at=ends_at,
                raw=alert,
            )
        )

    return contexts


def parse_first_alert(payload: dict) -> AlertContext | None:
    """Primeiro alerta válido do webhook ou None."""
    alerts = parse_webhook(payload)
    return alerts[0] if alerts else None
