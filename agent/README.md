# Grafana Alert Agent

Agente Python que recebe alertas do Grafana via webhook, coleta contexto
automático (métricas do Prometheus + logs do Loki) e gera uma análise
com uma LLM (via LangChain) para ajudar o desenvolvedor a identificar a causa.

## Estrutura

```
agent/
├── main.py              # FastAPI — recebe o webhook (202 + background)
├── agent.py             # Orquestrador principal + factory LangChain
├── rabbit_publisher.py  # RabbitMQ (filas analysis / resolved)
├── config.py            # Configuração via variáveis de ambiente
├── grafana_client.py    # API REST do Grafana
├── alert_parser.py      # Parser do payload do webhook
├── context_collector.py # Coleta métricas e logs
├── analysis.py          # System prompt + montagem do contexto
├── Dockerfile
├── pyproject.toml       # Dependências (gerenciadas pelo UV)
├── .env.example
└── test_webhook.py      # Teste local
```

## Providers de LLM suportados

O agente usa LangChain como camada de abstração, permitindo trocar o provider
apenas via variáveis de ambiente, sem alterar código.

| `LLM_PROVIDER` | Modelos de exemplo                          | `LLM_BASE_URL` necessário? |
|----------------|---------------------------------------------|---------------------------|
| `anthropic`    | `claude-sonnet-4-20250514`, `claude-3-haiku-20240307` | Não |
| `openai`       | `gpt-4o`, `gpt-4o-mini`                     | Não |
| `openai`       | Qualquer modelo local no **LM Studio**      | Sim (ver abaixo) |

### Usando LM Studio (modelo local)

O LM Studio expõe uma API compatível com o padrão OpenAI. Basta configurar:

```env
LLM_PROVIDER=openai
LLM_MODEL=google/gemma-3-4b
LLM_API_KEY=lm-studio          # qualquer string, não é validada
LLM_BASE_URL=http://host.docker.internal:1234/v1
```

> `host.docker.internal` permite que o container acesse o LM Studio rodando no seu Mac.

## Setup

### 1. Configure as variáveis de ambiente

```bash
cp .env.example .env
# Edite .env com o provider e tokens desejados
```

### 2. Instale as dependências (desenvolvimento local)

```bash
# Instala o UV se ainda não tiver
curl -LsSf https://astral.sh/uv/install.sh | sh

# Cria o ambiente virtual e instala as dependências
uv sync

# Rode o servidor localmente
uv run uvicorn main:app --reload
```

### 3. RabbitMQ (local)

O deploy em produção usa o broker na stack Docker da raiz (`rabbitmq` no
`docker-compose.yml`, AMQP em `localhost:5672`). Para desenvolvimento local com
`uvicorn`, aponte `RABBITMQ_URL` para `amqp://guest:guest@localhost:5672/` (subindo
o Compose antes: `docker compose up -d` na raiz do repositório).

O agente em si é implantado no **Kubernetes** (Kind) — ver README da raiz, seção
“Deploy do agente”.

### 4. Configure o webhook no Grafana

1. Acesse **Alerting → Contact points → New contact point**
2. Tipo: **Webhook**
3. URL: `http://alert-agent:8000/webhook` (dentro do Docker)
   ou `http://localhost:9093/webhook` (fora do cluster: port-forward do deploy na porta **9093**)
4. Salve e adicione ao seu **Notification policy**

### 5. Teste localmente

```bash
uv run python test_webhook.py
```

## Endpoints

| Método | Path       | Descrição |
|--------|------------|-----------|
| GET    | /health    | Health check |
| POST   | /webhook   | Recebe alertas do Grafana; responde **202 Accepted** (`{"status":"accepted"}`) e publica em background no RabbitMQ (`weather.agent.analysis` ou `weather.agent.resolved`) |

## Variáveis de ambiente

| Variável            | Descrição                                              | Padrão                      |
|---------------------|--------------------------------------------------------|-----------------------------|
| `GRAFANA_URL`       | URL do Grafana                                         | `http://grafana:3000`       |
| `GRAFANA_TOKEN`     | Token da service account (glsa_...)                   | obrigatório                 |
| `LLM_PROVIDER`      | Provider da LLM: `anthropic` ou `openai`              | `anthropic`                 |
| `LLM_MODEL`         | Nome do modelo a usar                                  | `claude-sonnet-4-20250514`  |
| `LLM_API_KEY`       | Chave de API do provider                               | obrigatório                 |
| `LLM_BASE_URL`      | URL base customizada (LM Studio, proxies OpenAI-compat)| vazio (usa padrão do provider)|
| `METRICS_LOOKBACK`  | Janela de tempo das métricas (segundos)               | `900`                       |
| `LOGS_LOOKBACK`     | Janela de tempo dos logs                               | `15m`                       |
| `RABBITMQ_ENABLED`  | Liga/desliga publicação AMQP                           | `true`                      |
| `RABBITMQ_URL`      | URL AMQP (`guest`/`guest` no dev)                      | `amqp://guest:guest@rabbitmq:5672/` |
| `RABBITMQ_EXCHANGE` | Exchange topic principal                               | `weather.agent`             |
| `RABBITMQ_ANALYSIS_QUEUE` / `RABBITMQ_ANALYSIS_ROUTING_KEY` | Fila / routing de análises LLM | `weather.agent.analysis` / `analysis` |
| `RABBITMQ_RESOLVED_QUEUE` / `RABBITMQ_RESOLVED_ROUTING_KEY` | Fila / routing de resolved      | `weather.agent.resolved` / `resolved` |
| `RABBITMQ_PUBLISH_TIMEOUT_SECONDS` | Timeout do publish com confirms          | `5.0`                       |
