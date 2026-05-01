# Grafana Alert Agent

Agente Python que recebe alertas do Grafana via webhook, coleta contexto
automático (métricas do Prometheus + logs do Loki) e gera uma análise
com uma LLM (via LangChain) para ajudar o desenvolvedor a identificar a causa.

## Estrutura

```
agent/
├── main.py              # FastAPI — recebe o webhook
├── agent.py             # Orquestrador principal + factory LangChain
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

### 3. Suba via Docker Compose

O serviço já está declarado no `docker-compose.yml` da raiz do projeto:

```bash
# Sobe apenas o agente (Grafana e demais serviços já devem estar rodando)
docker compose up alert-agent --build

# Ou sobe tudo junto
docker compose up --build
```

As variáveis de ambiente podem ser passadas no `.env` da raiz do projeto ou
diretamente na linha de comando:

```bash
LLM_PROVIDER=openai LLM_MODEL=gpt-4o LLM_API_KEY=sk-... docker compose up alert-agent --build
```

### 4. Configure o webhook no Grafana

1. Acesse **Alerting → Contact points → New contact point**
2. Tipo: **Webhook**
3. URL: `http://alert-agent:8000/webhook` (dentro do Docker)
   ou `http://localhost:8001/webhook` (se testar de fora)
4. Salve e adicione ao seu **Notification policy**

### 5. Teste localmente

```bash
uv run python test_webhook.py
```

## Endpoints

| Método | Path       | Descrição                        |
|--------|------------|----------------------------------|
| GET    | /health    | Health check                     |
| POST   | /webhook   | Recebe alertas do Grafana        |

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
