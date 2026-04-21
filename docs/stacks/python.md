# Guia de Stack — Python

Checklist prático para habilitar observabilidade **sem SDK no código** em uma aplicação
Python, seguindo o modelo descrito em [`../observability-playbook.md`](../observability-playbook.md).

A POC deste repositório (`app/main.py`) é a referência concreta. Este guia destaca o que
**qualquer squad Python** precisa fazer para replicar o modelo.

---

## 1. Pré-requisitos

- Python 3.9+ (a POC usa 3.12 — veja `app/Dockerfile`)
- Uma stack web suportada pela auto-instrumentação OTel (ex.: FastAPI, Flask, Django)
- Um driver de DB suportado (ex.: `psycopg2`, `pymysql`, `redis`, `pymongo`)

Lista completa de libs instrumentadas: <https://github.com/open-telemetry/opentelemetry-python-contrib>.

---

## 2. Alterações obrigatórias na aplicação

A premissa é "zero SDK OTel no código". O que **precisa** mudar:

### 2.1 Logs em JSON no `stdout`

Adicione ao `requirements.txt`:

```
python-json-logger==2.0.7
```

E substitua o setup de logging (`main.py`):

```python
import logging
from pythonjsonlogger import jsonlogger

handler = logging.StreamHandler()
handler.setFormatter(jsonlogger.JsonFormatter(
    fmt="%(asctime)s %(name)s %(levelname)s %(message)s",
    datefmt="%Y-%m-%dT%H:%M:%S",
))
logging.basicConfig(level=logging.INFO, handlers=[handler])
logger = logging.getLogger(__name__)
```

Resultado: cada log vira um objeto JSON indexável no Loki. Quando o Operator injeta
`OTEL_PYTHON_LOG_CORRELATION=true`, os campos `trace_id`, `span_id` e
`resource.service.name` são adicionados automaticamente.

Exemplo de saída (visto em produção):

```json
{
  "asctime": "2026-04-21T14:16:10",
  "name": "main",
  "levelname": "INFO",
  "message": "GET /weather called",
  "city": "saopaulo",
  "trace_id": "b5c2061b6744b1f765c9831516ab164e",
  "span_id": "18dfd9a0306db530",
  "resource.service.name": "weather.api",
  "trace_sampled": "True"
}
```

### 2.2 Não importar SDK OTel

**NÃO** colocar no `requirements.txt`:

```
# ❌ NÃO
opentelemetry-sdk
opentelemetry-exporter-*
opentelemetry-instrumentation-*
```

Essas libs vêm do **Init Container**. Ter versões no `requirements.txt` cria risco de
**colisão** (duas instâncias do SDK no mesmo processo, resultando em spans duplicados ou
silêncio).

A **única** exceção é `opentelemetry-api` (só interfaces) caso a app queira emitir métricas
customizadas — ver [§3](#3-métricas-customizadas-opcional).

---

## 3. Métricas customizadas (opcional)

Se a squad quer métricas de negócio (exemplo da POC: contagem de requests por cidade):

```
# requirements.txt
opentelemetry-api>=1.20.0
```

```python
# main.py  — igual à POC app/main.py
from opentelemetry import metrics

_meter = metrics.get_meter("weather.api")

city_requests_counter = _meter.create_counter(
    name="weather.city.requests",
    description="Requests a /weather por cidade",
    unit="1",
)

# Uso
city_requests_counter.add(1, {"city": city, "env": ENV})
```

**Regras de cardinalidade**:
- Attributes devem ser **de baixa cardinalidade**: `city` ok se for finito; `user_id` **nunca**.
- Métricas sempre com `unit` (`1`, `ms`, `bytes`, ...).
- Nomes seguem `<dominio>.<recurso>.<açao>` (ex.: `weather.city.requests`, `weather.validation.errors`).

O SDK que materializa esse meter é injetado pelo Init Container. A API é leve e sem deps
externas, então o `requirements.txt` da app permanece enxuto.

---

## 4. Pegadinhas (anti-patterns conhecidos)

### 4.1 `psycopg2` + `cursor_factory` quebra a instrumentação SQL

**Sintoma:** traces aparecem no Jaeger com spans HTTP mas **sem** spans de SQL.

**Causa:**

```python
# ❌ Quebra spans SQL
cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
```

O `opentelemetry-instrumentation-psycopg2` instrumenta `psycopg2.connect()` sobrescrevendo
`connection.cursor_factory = TracedCursorFactory`. Passar `cursor_factory=RealDictCursor`
diretamente no `cursor()` **anula** o factory instrumentado.

**Solução (já aplicada em `app/main.py` da POC):**

```python
# ✅ Deixa o OTel controlar o cursor_factory
cur = conn.cursor()
# Converte tuplas em dict manualmente
col_names = [desc[0] for desc in cur.description] if cur.description else []
rows = [dict(zip(col_names, row)) for row in cur.fetchall()]
```

### 4.2 `uvicorn --workers > 1` + logging setup em `if __name__ == "__main__"`

Se o setup de logging estiver num bloco que só roda no main do uvicorn master, os workers
não terão o JSON formatter. Coloque o setup de logging no **nível de módulo** (como em
`app/main.py`) para que cada worker herde.

### 4.3 `DeprecationWarning: PYTHONPATH`

Alguns runtimes reclamam quando `PYTHONPATH` é injetado. A solução da POC é usar
`python:3.12-slim` como base; distros Alpine tendem a causar problemas de compatibilidade
com o agente OTel por causa do `musl`.

### 4.4 Healthchecks inflando spans

Endpoints `/live`, `/ready` são chamados pelo kubelet constantemente. Excluí-los:

```yaml
# No patch-instrumentation.yaml do overlay
spec:
  python:
    env:
      - name: OTEL_PYTHON_FASTAPI_EXCLUDED_URLS
        value: "live,ready,healthz,metrics"
```

---

## 5. `Deployment` mínimo (exemplo)

Referência: `k8s/base/deployment.yaml` da POC.

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: weather-api
spec:
  replicas: 1
  selector:
    matchLabels:
      app: weather-api
  template:
    metadata:
      labels:
        app: weather-api
        app_name: weather.api        # ← alinhado com OTEL_SERVICE_NAME
        env: dev                     # ← sobrescrito pelo overlay
      annotations:
        instrumentation.opentelemetry.io/inject-python: "true"   # ← gatilho OTel
    spec:
      containers:
        - name: weather-api
          image: registry.org/weather/weather-api:<tag>
          ports: [{ containerPort: 8000 }]
          env:
            - { name: APP_NAME, value: weather.api }
            - { name: ENV,      valueFrom: { secretKeyRef: { name: weather-secret, key: ENV } } }
          # Sem nenhuma env var OTEL_* aqui — elas vêm do CR Instrumentation
```

---

## 6. `Instrumentation` mínimo (exemplo)

Referência: `k8s/base/instrumentation.yaml` + `k8s/overlays/prod/patch-instrumentation.yaml`.

```yaml
apiVersion: opentelemetry.io/v1alpha1
kind: Instrumentation
metadata:
  name: weather-instrumentation
spec:
  exporter:
    endpoint: http://otel-collector.observability.svc.cluster.local:4318
  propagators: [tracecontext, baggage]
  python:
    env:
      - { name: OTEL_LOGS_EXPORTER,            value: otlp }
      - { name: OTEL_METRICS_EXPORTER,         value: otlp }
      - { name: OTEL_TRACES_EXPORTER,          value: otlp }
      - { name: OTEL_PYTHON_LOG_CORRELATION,   value: "true" }
      - { name: OTEL_PYTHON_FASTAPI_EXCLUDED_URLS, value: "live,ready,healthz,metrics" }
      - { name: OTEL_SERVICE_NAME,             value: weather.api }
      - name: OTEL_RESOURCE_ATTRIBUTES
        value: "service.name=weather.api,deployment.environment=prod,application.name=weather.api"
```

---

## 7. Checklist por squad Python

- [ ] `requirements.txt` **sem** pacotes OTel (exceto `opentelemetry-api` se emitir métricas customizadas)
- [ ] `python-json-logger` no `requirements.txt`
- [ ] Setup de logging JSON no nível de módulo, não dentro de `if __name__ == "__main__"`
- [ ] `psycopg2`: usar `conn.cursor()` sem `cursor_factory`; converter rows manualmente
- [ ] `Deployment` com annotation `instrumentation.opentelemetry.io/inject-python: "true"`
- [ ] Labels `app_name` e `env` alinhadas com os atributos OTel
- [ ] `Instrumentation` CR no mesmo namespace do Pod
- [ ] `OTEL_RESOURCE_ATTRIBUTES` com `service.name`, `deployment.environment`, `application.name` por overlay
- [ ] Healthcheck URLs excluídas via `OTEL_PYTHON_<FRAMEWORK>_EXCLUDED_URLS`
- [ ] Validação e2e (ver [`observability-playbook.md §9`](../observability-playbook.md#9-validação-end-to-end))

---

## 8. Referências

- App de referência neste repo: [`app/main.py`](../../app/main.py)
- POC detalhada: [`../observability-sidecar-pattern.md`](../observability-sidecar-pattern.md)
- Libs instrumentadas: <https://github.com/open-telemetry/opentelemetry-python-contrib/tree/main/instrumentation>
- Variáveis de ambiente Python: <https://opentelemetry-python.readthedocs.io/en/latest/sdk/environment_variables.html>
