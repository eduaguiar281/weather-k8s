# Grafana Alert Agent

Agente Python que recebe alertas do Grafana via webhook, coleta contexto
automático (métricas do Prometheus + logs do Loki) e gera uma análise
com uma LLM (via LangChain) para ajudar o desenvolvedor a identificar a causa.

## Estrutura

O código vive no pacote Python **`alert_agent`**, organizado por responsabilidade (SRP, baixo acoplamento: **core** não importa módulos de **infra**; a montagem faz-se em **`bootstrap`**).

```
agent/
├── main.py                     # Shim → exporta app FastAPI (uvicorn main:app)
├── alert_agent/
│   ├── config.py               # Settings (Pydantic) — variáveis de ambiente
│   ├── bootstrap.py            # Composition root: Grafana + Rabbit + LLM + SreAnalysisAgent
│   ├── core/                   # Caso de uso / domínio
│   │   ├── ports.py            # Protocols (Grafana, LLM chat, publisher, …)
│   │   ├── alert_parser.py
│   │   ├── analysis.py
│   │   ├── context_collector.py
│   │   └── sre_analysis_agent.py   # Orquestrador «agente SRE análise»
│   ├── infra/                  # Adaptadores externos
│   │   ├── grafana/client.py
│   │   ├── rabbitmq/publisher.py
│   │   ├── blob/llm_results.py
│   │   └── llm/                # factory LangChain + LlmChatService (invocação DRY + tokens)
│   └── presentation/
│       └── app.py              # FastAPI, rotas, lifespan
├── Dockerfile
├── pyproject.toml
├── .env.example
└── test_webhook.py
```

### Arquitetura (camadas)

```mermaid
flowchart TB
  subgraph presentation [presentation]
    Http[FastAPI app]
  end
  subgraph bootstrap [bootstrap]
    Build[build_sre_analysis_agent]
  end
  subgraph core [core]
    Sre[SreAnalysisAgent]
    Prompts[analysis e alert_parser]
    Ctx[ContextCollector]
  end
  subgraph infraLayer [infra]
    Grafana[GrafanaClient]
    Rabbit[RabbitPublisher]
    Blob[Blob llm_results]
    Llm[LlmChatService]
  end
  Http -->|"rotas webhook e teste LLM"| Sre
  Http -->|"lifespan e listagem SAS"| Blob
  Build --> Sre
  Build --> Ctx
  Build --> Grafana
  Build --> Rabbit
  Build --> Llm
  Sre --> Prompts
  Sre --> Ctx
  Ctx -.->|"Protocol"| Grafana
  Sre -.->|"Protocol"| Llm
  Sre -.->|"Protocol"| Rabbit
  Sre -.->|"persistir análise"| Blob
```

- **`presentation`**: HTTP apenas; não contém lógica de análise. Usa **Blob** direto só para operações operacionais (garantir container no startup e listar SAS em `/llm/download-urls`). O fluxo **alerta → análise** passa pelo **`SreAnalysisAgent`** em core.
- **`core`**: `SreAnalysisAgent` e `ContextCollector` dependem de **Protocols** em `ports.py` (`LlmChatPort`, `GrafanaDatasourcePort`, `AlertEventPublisher`, …), não de classes concretas de infra.
- **`bootstrap`**: único sítio que instancia adaptadores (`GrafanaClient`, `RabbitPublisher`, `LlmChatService`) e injeta no agente.

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

### Kubernetes / Kind (`deploy-agent.sh`)

Variáveis usadas pelo script que gera `agent-secret` (exporte no shell ou mantenha no `~/.zshrc`):

- `GRAFANA_URL=http://host.docker.internal:3000` — o Grafana **não** está na rede `kind_bridge`; use a porta exposta no host pelo Compose (**3000**).
- `RABBITMQ_URL=amqp://guest:guest@host.docker.internal:5672/`
- `LLM_BASE_URL=http://host.docker.internal:<porta>/v1` — caminho deve terminar em **`/v1`**, não `/api/v1` (compatível LangChain/OpenAI SDK).

Veja também o README na raiz, seção «Deploy do agente».

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

# (Alternativa) pip: a primeira instalação pode demorar vários minutos (LangChain /
# dependências ML). Sem saída visível parece “travar”; use por exemplo:
#   pip install -e ".[dev]"
# Testes: `pytest tests -q --cov=alert_agent` (timeout global 120s via pytest-timeout).

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
| POST   | /webhook   | Recebe alertas do Grafana; responde **202 Accepted** (`{"status":"accepted"}`) e publica em background na fila **`weather.agent.analysis`** (mensagens JSON com `kind: "analysis"` ou `kind: "resolved"`) |
| POST   | /llm/test  | Mensagem livre à LLM (validação do provider) |
| GET    | /llm/download-urls | Lista SAS de leitura das pastas em `llm_results/` no Blob (requer `BLOB_STORAGE`) |

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
| `RABBITMQ_ANALYSIS_QUEUE` / `RABBITMQ_ANALYSIS_ROUTING_KEY` | Fila / routing (**todas** as mensagens: análises LLM e resolved); consumidores distingam pelo campo `"kind"` | `weather.agent.analysis` / `analysis` |
| `RABBITMQ_ANALYSIS_SINGLE_ACTIVE_CONSUMER` | `true`: declara a fila com `x-single-active-consumer` (FIFO entre réplicas). `false`: compatível com RabbitMQ onde a mesma queue já existe **sem** esse argumento (ex. volume Docker antigo); preferível antes recrear filas com `scripts/rabbitmq-reset-weather-agent-queues.sh` na raíz do repo | `true` |
| `RABBITMQ_PUBLISH_TIMEOUT_SECONDS` | Timeout do publish com confirms          | `5.0`                       |

Com `single_active_consumer=true`, ainda há DLX ligado a **`weather.agent.analysis.dlq`**. Para ordem estrita aos consumidores, use prefetch baixo (ex. `prefetch_count=1`). Alterar argumentos de uma fila existente pode exigir apagar/redeclarar a queue no RabbitMQ (erro tipo `PRECONDITION_FAILED`). Com fila legada sem SAC, ponha **`RABBITMQ_ANALYSIS_SINGLE_ACTIVE_CONSUMER=false`** temporariamente **ou** apague as queues do agent.
