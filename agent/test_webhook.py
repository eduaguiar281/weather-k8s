#!/usr/bin/env python3
"""
Simula um webhook do Grafana Alerting para testar o agente localmente.
Execute com: python test_webhook.py

Com agente no Kind + port-forward do deploy: use http://localhost:9093/webhook
(ver scripts/deploy-agent.sh). Com uvicorn local na porta padrão: 8000.
"""
import httpx
import json

AGENT_URL = "http://localhost:8000/webhook"

# Payload no formato exato que o Grafana Alerting envia
PAYLOAD = {
    "receiver": "alert-agent",
    "status": "firing",
    "alerts": [
        {
            "status": "firing",
            "labels": {
                "alertname": "HighErrorRate",
                "severity": "critical",
                "job": "api-gateway",
                "namespace": "production",
                "env": "prod",
            },
            "annotations": {
                "summary": "Taxa de erro HTTP acima de 5% nos últimos 5 minutos",
                "description": "O serviço api-gateway está retornando mais de 5% de erros 5xx.",
                "runbook_url": "https://wiki.empresa.com/runbooks/high-error-rate",
            },
            "startsAt": "2025-04-30T10:00:00Z",
            "endsAt": "0001-01-01T00:00:00Z",
            "generatorURL": "http://grafana:3000/alerting/...",
            "fingerprint": "abc123def456",
        }
    ],
    "groupLabels": {"alertname": "HighErrorRate"},
    "commonLabels": {"job": "api-gateway", "namespace": "production"},
    "commonAnnotations": {},
    "externalURL": "http://grafana:3000",
    "title": "[FIRING:1] HighErrorRate",
    "message": "Taxa de erro HTTP acima de 5%",
}


def test():
    print("Enviando webhook de teste para o agente...")
    print(f"URL: {AGENT_URL}\n")

    with httpx.Client(timeout=120) as client:
        r = client.post(AGENT_URL, json=PAYLOAD)

    print(f"Status: {r.status_code}\n")
    try:
        data = r.json()
        print("=== RESPOSTA DO AGENTE ===\n")
        print(json.dumps(data, indent=2, ensure_ascii=False))
        if r.status_code == 202:
            print(
                "\n(202 Accepted) O processamento é assíncrono; a análise LLM vai para "
                "a fila RabbitMQ `weather.agent.analysis` quando o alerta está firing/pending."
            )
    except Exception:
        print(r.text)


if __name__ == "__main__":
    test()
