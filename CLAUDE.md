# Contexto do projeto (Claude / assistentes)

Este repositório inclui o serviço Python **alert-agent** em `agent/`, organizado pelo pacote `alert_agent`.

## Arquitetura do alert-agent

Referência longa: `agent/README.md` (secção **Arquitetura**).

- **`alert_agent/core/`** — caso de uso: `SreAnalysisAgent`, parsing de alertas, montagem de prompts, `ContextCollector`. **Não importar** `infra/` nem `presentation/`. Usar apenas **`Ports`/`Protocol`** definidos em `alert_agent/core/ports.py` para dependências externas.

- **`alert_agent/infra/`** — adaptadores: Grafana, RabbitMQ, armazenamento Blob, factory LangChain e `LlmChatService`.

- **`alert_agent/presentation/`** — FastAPI (rotas, lifespan); sem lógica de negócio.

- **`alert_agent/bootstrap.py`** — único composition root: cria implementações concretas e injeta no agente.

- **`alert_agent/config.py`** — Pydantic `BaseSettings`; literais nos campos são *defaults*, não “valores fixos” — sobrescritos por variáveis de ambiente (`GRAFANA_URL`, `LLM_MODEL`, etc.).

## Princípios ao alterar código Python em `agent/`

1. **Responsabilidade única** e **DRY** (ex.: chamadas LLM via `LlmChatService`; parse de webhook reutilizado no core).

2. **Desacoplamento**: novo sistema externo → `infra/` + port em `ports.py` quando o core precisar; wiring em `bootstrap.py`.

3. **`agent/main.py`** permanece apenas como entrypoint/shim para `uvicorn main:app`.

A regra equivalente para o Cursor está em `.cursor/rules/alert-agent-layered-architecture.mdc`.
