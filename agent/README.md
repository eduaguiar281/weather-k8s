# Grafana Alert Agent

Agente Python que recebe alertas do Grafana via webhook, coleta contexto
automático (métricas do Prometheus + logs do Loki) e gera uma análise
com a Claude API para ajudar o desenvolvedor a identificar a causa.

## Estrutura

```
grafana-agent/
├── app/
│   ├── main.py              # FastAPI — recebe o webhook
│   ├── agent.py             # Orquestrador principal
│   ├── config.py            # Configuração via variáveis de ambiente
│   ├── tools/
│   │   ├── grafana_client.py    # API REST do Grafana
│   │   ├── alert_parser.py      # Parser do payload do webhook
│   │   └── context_collector.py # Coleta métricas e logs
│   └── prompts/
│       └── analysis.py      # System prompt + montagem do contexto
├── Dockerfile
├── docker-compose.yml
├── requirements.txt
├── .env.example
└── test_webhook.py          # Teste local
```

## Setup

### 1. Configure as variáveis de ambiente

```bash
cp .env.example .env
# Edite .env com seus tokens
```

### 2. Suba os containers

```bash
# Se o Grafana já está rodando em outro compose, só suba o agente:
docker compose up alert-agent --build

# Se quiser subir tudo junto:
docker compose up --build
```

### 3. Configure o webhook no Grafana

1. Acesse **Alerting → Contact points → New contact point**
2. Tipo: **Webhook**
3. URL: `http://alert-agent:8000/webhook` (dentro do Docker)
   ou `http://localhost:8000/webhook` (se testar de fora)
4. Salve e adicione ao seu **Notification policy**

### 4. Teste localmente

```bash
pip install httpx
python test_webhook.py
```

## Endpoints

| Método | Path       | Descrição                        |
|--------|------------|----------------------------------|
| GET    | /health    | Health check                     |
| POST   | /webhook   | Recebe alertas do Grafana        |

## Variáveis de ambiente

| Variável            | Descrição                              | Padrão           |
|---------------------|----------------------------------------|------------------|
| `GRAFANA_URL`       | URL do Grafana                         | http://grafana:3000 |
| `GRAFANA_TOKEN`     | Token da service account (glsa_...)   | obrigatório      |
| `ANTHROPIC_API_KEY` | Chave da API Anthropic                 | obrigatório      |
| `METRICS_LOOKBACK`  | Janela de tempo das métricas (seg)    | 900              |
| `LOGS_LOOKBACK`     | Janela de tempo dos logs              | 15m              |
