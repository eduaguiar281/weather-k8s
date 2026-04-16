# Observabilidade sem Instrumentação: Padrão Init Container (Auto-Instrumentation)

## Contexto

Esta POC demonstra uma abordagem alternativa à instrumentação manual com o SDK do OpenTelemetry.
O objetivo é alcançar **métricas, traces e logs correlacionados** com o mínimo de alterações
na aplicação, usando infraestrutura Kubernetes como único ponto de configuração.

---

## Comparação de Abordagens

| Aspecto | **Produção (SDK direto)** | **Esta POC (Auto-Instrumentation)** |
|---|---|---|
| Instrumentação | No código da aplicação | Via Init Container injetado pelo Operator |
| Dependências OTel | `opentelemetry-sdk`, `opentelemetry-exporter-*` no `requirements.txt` | Nenhuma dependência OTel na aplicação |
| Configuração do exporter | Código Python (`TracerProvider`, `BatchSpanProcessor`) | Variáveis de ambiente injetadas pelo Operator |
| Propagadores | `set_global_textmap(TraceContextTextMapPropagator())` no código | `propagators: [tracecontext, baggage]` no CR `Instrumentation` |
| Spans customizados | `with tracer.start_as_current_span("minha-operacao"):` | Não disponível sem código |
| Atributos customizados | `span.set_attribute("chave", "valor")` | Não disponível sem código |
| Portabilidade | Aplicação carrega seu próprio SDK | Aplicação é agnóstica; comportamento muda pelo cluster |

---

## Arquitetura

```
┌─────────────────────────────────────────────────────────────────────────────┐
│  KUBERNETES CLUSTER (kind)                                                  │
│                                                                             │
│  ┌──────────────────────────────────────────────────────────────────────┐   │
│  │  Pod: weather-api                           namespace: weather        │   │
│  │                                                                      │   │
│  │  ┌─────────────────────────┐   shared volume   ┌──────────────────┐  │   │
│  │  │   INIT CONTAINER        │ ─────────────────► │  CONTAINER       │  │   │
│  │  │                         │  /otel-auto-       │  weather-api     │  │   │
│  │  │  autoinstrumentation-   │  instrumentation-  │                  │  │   │
│  │  │  python:0.60b1          │  python/           │  FastAPI         │  │   │
│  │  │                         │                    │  psycopg2        │  │   │
│  │  │  copia libs OTel →      │                    │                  │  │   │
│  │  │  opentelemetry-sdk      │                    │  PYTHONPATH ◄──────── env vars
│  │  │  instrumentation-       │                    │  injetado pelo   │  │   │
│  │  │  fastapi                │                    │  Operator        │  │   │
│  │  │  instrumentation-       │                    │                  │  │   │
│  │  │  psycopg2               │                    │  ↕ spans/metrics │  │   │
│  │  │  ...                    │                    │  via OTLP HTTP   │  │   │
│  │  └─────────────────────────┘                    └────────┬─────────┘  │   │
│  │                                                          │             │   │
│  └──────────────────────────────────────────────────────────┼────────────┘   │
│                                                             │                │
│  ┌──────────────────────────────────────────────────────────┼────────────┐   │
│  │  namespace: monitoring                                   │            │   │
│  │                                                          │            │   │
│  │  Promtail DaemonSet                                      │            │   │
│  │  (coleta stdout/stderr dos pods via /var/log/pods)       │            │   │
│  └──────────────────────────────────────────────────────────┼────────────┘   │
│                                                             │                │
└─────────────────────────────────────────────────────────────┼────────────────┘
                                                              │
                              ┌───────────────────────────────▼──────────────────┐
                              │  DOCKER COMPOSE  (rede: observability_observ...)  │
                              │                                                   │
                              │  ┌───────────────┐   traces   ┌───────────────┐  │
                              │  │ OTel Collector │ ─────────► │    Jaeger     │  │
                              │  │ 172.23.0.50   │   metrics  │               │  │
                              │  │               │ ─────────► │  Prometheus   │  │
                              │  └───────────────┘   logs     │               │  │
                              │                      ──────►  │     Loki      │  │
                              │  ┌───────────────┐            │  172.23.0.51  │  │
                              │  │    Grafana    │ ◄──────────┤               │  │
                              │  │  (dashboards) │            └───────────────┘  │
                              │  └───────────────┘                               │
                              └──────────────────────────────────────────────────┘
```

### Como o Init Container funciona

O **OpenTelemetry Operator** monitora os pods e, ao detectar a anotação
`instrumentation.opentelemetry.io/inject-python: "true"`, injeta automaticamente:

1. Um **Init Container** que copia as bibliotecas OTel para um volume compartilhado
2. **Variáveis de ambiente** no container da aplicação (`PYTHONPATH`, `OTEL_*`)
3. A aplicação inicia com `PYTHONPATH` apontando para o volume — o `sitecustomize.py`
   do OTel executa **antes** do código da aplicação e aplica monkey-patching em:
   - `fastapi` / `starlette` → spans HTTP
   - `psycopg2` → spans de query SQL
   - `logging` → injeção de `trace_id` e `span_id` nos logs

---

## Onde está configurado nos YAMLs

### 1. Anotação no Deployment — ativa a injeção

**Arquivo:** `k8s/deployment.yaml`

```yaml
spec:
  template:
    metadata:
      annotations:
        instrumentation.opentelemetry.io/inject-python: "true"  # ← esta linha
```

Esta única anotação é o gatilho. O Operator lê ela e injeta o Init Container
no Pod antes de subir. Sem ela, a aplicação sobe sem nenhuma instrumentação.

---

### 2. Custom Resource `Instrumentation` — define o comportamento

**Arquivo:** `k8s/instrumentation.yaml`

```yaml
apiVersion: opentelemetry.io/v1alpha1
kind: Instrumentation
metadata:
  name: weather-instrumentation
  namespace: weather
spec:
  exporter:
    endpoint: http://172.23.0.50:4318   # OTel Collector (IP fixo na rede kind_bridge)
  propagators:
    - tracecontext                       # W3C Trace Context
    - baggage
  python:
    env:
      - name: OTEL_LOGS_EXPORTER
        value: otlp                      # exporta logs via OTLP (além de stdout)
      - name: OTEL_PYTHON_LOG_CORRELATION
        value: "true"                    # injeta trace_id/span_id nos logs Python
      - name: OTEL_SERVICE_NAME
        value: weather-api
```

Este CR define **toda** a configuração que no modelo SDK seria feita no código:
- Para onde enviar (`endpoint`)
- Como propagar contexto (`propagators`)
- Qual exporter de logs usar (`OTEL_LOGS_EXPORTER`)
- Como correlacionar logs com traces (`OTEL_PYTHON_LOG_CORRELATION`)

---

### 3. O que o Operator injeta no Pod (gerado automaticamente)

Ao aplicar o deployment com a anotação, o Operator transforma o Pod para incluir:

```yaml
# Gerado pelo Operator — não está nos nossos YAMLs, é automático
initContainers:
  - name: opentelemetry-auto-instrumentation-python
    image: ghcr.io/open-telemetry/opentelemetry-operator/autoinstrumentation-python:0.60b1
    command: ["cp", "-r", "/autoinstrumentation/.", "/otel-auto-instrumentation-python"]
    volumeMounts:
      - mountPath: /otel-auto-instrumentation-python
        name: opentelemetry-auto-instrumentation-python

containers:
  - name: weather-api
    env:
      - name: PYTHONPATH
        value: "/otel-auto-instrumentation-python/opentelemetry/instrumentation/auto_instrumentation\
                :/otel-auto-instrumentation-python"
      - name: OTEL_TRACES_EXPORTER
        value: otlp
      - name: OTEL_METRICS_EXPORTER
        value: otlp
      - name: OTEL_EXPORTER_OTLP_ENDPOINT
        value: http://172.23.0.50:4318
      - name: OTEL_EXPORTER_OTLP_PROTOCOL
        value: http/protobuf
      - name: OTEL_SERVICE_NAME
        value: weather-api
      - name: OTEL_PYTHON_LOG_CORRELATION
        value: "true"
      - name: OTEL_PROPAGATORS
        value: tracecontext,baggage
```

---

### 4. Coleta de logs — Promtail DaemonSet

**Arquivo:** `k8s/promtail/configmap.yaml`

Os logs que a aplicação escreve em `stdout` são capturados pelo Promtail, que roda
como DaemonSet em cada nó do cluster:

```yaml
scrape_configs:
  - job_name: kubernetes-pods
    pipeline_stages:
      - cri: {}
      - multiline:                    # agrupa stack traces em uma única entrada
          firstline: '^\d{4}-\d{2}-\d{2}...'
      - regex:                        # extrai namespace, pod, container do path
          expression: '/var/log/pods/(?P<namespace>[^_]+)_(?P<pod>[^_]+)...'
          source: filename
      - labels:
          namespace:
          pod:
          container:
      - regex:                        # detecta se é log da app ou do SDK OTel
          expression: '(?P<otel_sdk_log>otel-auto-instrumentation-python|...)'
      - template:
          source: log_source
          template: '{{ if .otel_sdk_log }}otel_sdk{{ else }}app{{ end }}'
      - labels:
          log_source:                 # label: "app" ou "otel_sdk"
    static_configs:
      - labels:
          __path__: /var/log/pods/*/*/*.log
```

---

## Alterações na Aplicação

A premissa desta POC era **não instrumentar a aplicação**. As únicas mudanças feitas
no código foram funcionais, não de observabilidade:

### `requirements.txt` — 1 dependência adicionada

```diff
  fastapi==0.110.2
  uvicorn==0.29.0
  psycopg2-binary==2.9.9
+ python-json-logger==2.0.7
```

**Por quê:** Para que os logs saiam em formato JSON estruturado, facilitando a
indexação no Loki e a extração de campos como `trace_id`, `level` e `message`.
Não é código OTel — é formatação de log padrão Python.

---

### `main.py` — 2 alterações

#### Alteração 1: configuração do formatter de log JSON

```diff
+ from pythonjsonlogger import jsonlogger
+
+ handler = logging.StreamHandler()
+ handler.setFormatter(jsonlogger.JsonFormatter(
+     fmt="%(asctime)s %(name)s %(levelname)s %(message)s",
+     datefmt="%Y-%m-%dT%H:%M:%S",
+ ))
+ logging.basicConfig(level=logging.INFO, handlers=[handler])
  logger = logging.getLogger(__name__)
```

**Por quê:** Sem JSON, o OTel injeta `trace_id` e `span_id` no log mas em formato
de texto livre, dificultando a busca no Loki. Com JSON, cada campo é indexável.

---

#### Alteração 2: cursor psycopg2 sem `cursor_factory` explícito

```diff
- cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
+ cur = conn.cursor()

- rows = cur.fetchall()
+ col_names = [desc[0] for desc in cur.description] if cur.description else []
+ rows = [dict(zip(col_names, row)) for row in cur.fetchall()]
```

**Por quê:** O `opentelemetry-instrumentation-psycopg2` instrumenta `psycopg2.connect()`
e define `connection.cursor_factory = TracedCursorFactory`. Passar
`cursor_factory=RealDictCursor` diretamente no `cursor()` **substitui** o
`TracedCursorFactory`, desabilitando silenciosamente a geração de spans SQL.

A solução é usar `cursor()` sem argumento (o OTel controla o cursor_factory) e
converter as tuplas retornadas em dicts manualmente via `cursor.description`.
O comportamento da API não muda — apenas os spans SQL passam a ser gerados.

---

## Resultado: o que aparece no Jaeger sem nenhum código OTel

Cada chamada a `GET /weather` gera automaticamente:

```
GET /weather  (38ms)
├── GET /weather http send  (starlette ASGI)
├── GET /weather http send  (starlette ASGI response)
└── SELECT  (5ms)
      db.system    = postgresql
      db.name      = weather-db
      db.statement = SELECT id, city, date, weather FROM weather
                     WHERE city = %s ORDER BY date
      db.user      = postgres
      net.peer.name = postgres
      net.peer.port = 5432
```

E cada log gerado pela aplicação inclui automaticamente:

```json
{
  "asctime": "2026-04-16T21:16:10",
  "name": "main",
  "levelname": "INFO",
  "message": "GET /weather called",
  "city": "saopaulo",
  "trace_id": "b5c2061b6744b1f765c9831516ab164e",
  "span_id": "18dfd9a0306db530",
  "resource.service.name": "weather-api",
  "trace_sampled": "True"
}
```

Permitindo correlação direta entre logs e traces no Grafana.
