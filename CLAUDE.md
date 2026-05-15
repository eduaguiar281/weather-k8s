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

## Padrões de testes (`agent/`)

- **Local:** testes automatizados em `agent/tests/` (pytest). Scripts manuais (ex.: HTTP contra um agente local) **não** devem expor funções chamadas `test_*` para o pytest não as recolher por engano.
- **Independência:** cada teste corre sozinho e em qualquer ordem. Evitar mutar singletons (`alert_agent.config.settings`) ou `os.environ` sem revert; usar `pytest.MonkeyPatch`, `with patch(...)` ou fixtures com teardown. Instâncias novas por teste quando houver estado interno (ex. caches em `ContextCollector`).
- **Camadas:** testes de `core/` exercitam lógica com **fakes** que cumprem os `Protocol` em `alert_agent/core/ports.py` — **não** importar `infra/` nem `presentation/` a partir de testes puramente de domínio.
- **Infra:** mock de I/O (HTTP, RabbitMQ, Blob, construtores LangChain) — a suíte deve passar **sem rede** nem serviços reais.
- **Presentation:** `TestClient` / `httpx` ASGI com dependências do agente **substituídas** (patch ou factory de app de teste), para não construir `GrafanaClient` real no import.
- **Cobertura:** meta do pacote `alert_agent` em ~80% de linhas (`pytest --cov=alert_agent`), salvo decisão em contrário no PR.
- **Timeout:** [agent/pyproject.toml](agent/pyproject.toml) define `timeout = 120` (pytest-timeout) para um teste bloqueado não pendurar a suíte.

## Formatação (`agent/`)

- Código Python sob **`agent/`** (pacote `alert_agent`, `tests/`, `main.py`, scripts como `test_webhook.py`): formatar com **[Black](https://black.readthedocs.io/)** (forma parte das dependências `dev` em [agent/pyproject.toml](agent/pyproject.toml)).
- Da pasta `agent/`: `uv run black alert_agent tests main.py test_webhook.py` (ou `pip install -e ".[dev]"` e o mesmo comando com `black`).
- Verificação sem alterar ficheiros: `uv run black --check alert_agent tests main.py test_webhook.py`.
- Black é um **formatador** de estilo, não um linter de regras semânticas (ex. ruff/flake8).

A regra equivalente para o Cursor está em `.cursor/rules/alert-agent-layered-architecture.mdc`.
