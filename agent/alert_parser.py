from dataclasses import dataclass, field


@dataclass
class AlertContext:
    """Representa um alerta recebido via webhook do Grafana Alerting."""

    title: str
    state: str                          # firing | resolved | pending
    message: str
    labels: dict[str, str]
    annotations: dict[str, str]
    generator_url: str
    fingerprint: str
    starts_at: str
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
    def severity(self) -> str:
        return self.labels.get("severity", "unknown")

    @property
    def runbook(self) -> str:
        return self.annotations.get("runbook_url", "")


def parse_webhook(payload: dict) -> list[AlertContext]:
    """
    Converte o payload do Grafana Alerting webhook em AlertContext.

    O Grafana envia um envelope com a chave 'alerts' contendo
    uma lista — cada item é um alerta individual.
    """
    alerts_raw = payload.get("alerts", [payload])   # fallback para payload direto
    contexts: list[AlertContext] = []

    for alert in alerts_raw:
        contexts.append(
            AlertContext(
                title=alert.get("labels", {}).get("alertname", "")
                    or payload.get("title", "Alerta sem título"),
                state=alert.get("status", "firing"),
                message=alert.get("annotations", {}).get("summary", "")
                    or alert.get("annotations", {}).get("message", ""),
                labels=alert.get("labels", {}),
                annotations=alert.get("annotations", {}),
                generator_url=alert.get("generatorURL", ""),
                fingerprint=alert.get("fingerprint", ""),
                starts_at=alert.get("startsAt", ""),
                raw=alert,
            )
        )

    return contexts
