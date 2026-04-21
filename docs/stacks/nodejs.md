# Guia de Stack — Node.js

Checklist prático para habilitar observabilidade em uma aplicação Node.js, seguindo o
modelo descrito em [`../observability-playbook.md`](../observability-playbook.md).

Diferente da POC do repositório (que é Python + FastAPI + psycopg2), o contexto aqui é
Node.js. O padrão é **exatamente o mesmo** — muda só a anotação de injeção e algumas
env vars específicas da auto-instrumentação Node.

---

## 1. Pré-requisitos

- Node.js 18+ (LTS recomendado)
- Framework suportado pela auto-instrumentação OTel: Express, Fastify, Koa, Hapi, NestJS
- Driver de DB suportado: `pg`, `mysql2`, `mongodb`, `ioredis`

Lista completa: <https://github.com/open-telemetry/opentelemetry-js-contrib/tree/main/plugins/node>.

---

## 2. Alterações obrigatórias na aplicação

### 2.1 Logs em JSON no `stdout`

Use **`pino`** (recomendado pela leveza e integração OTel):

```bash
npm install pino pino-http
```

```js
// src/logger.js
const pino = require('pino');

const logger = pino({
  level: process.env.LOG_LEVEL || 'info',
  // Pino já emite JSON por padrão. Só setamos os campos que queremos expostos.
  formatters: {
    level: (label) => ({ level: label }),
  },
  timestamp: pino.stdTimeFunctions.isoTime,
});

module.exports = logger;
```

```js
// src/app.js  (Express, por exemplo)
const express = require('express');
const pinoHttp = require('pino-http');
const logger = require('./logger');

const app = express();
app.use(pinoHttp({ logger }));

app.get('/hello', (req, res) => {
  req.log.info({ city: req.query.city }, 'hello called');
  res.json({ message: 'hello world' });
});
```

> **Alternativa:** `winston` + `winston-transport-json`. Pino costuma ter melhor integração
> com OTel pela forma como manipula o contexto do request.

### 2.2 Correlação log ↔ trace

A auto-instrumentação Node não injeta `trace_id`/`span_id` diretamente no logger (diferente
do Python, onde `OTEL_PYTHON_LOG_CORRELATION=true` já resolve). Em Node.js, a prática é:

**Opção A — `pino-opentelemetry-transport` (recomendado):**

```bash
npm install pino-opentelemetry-transport
```

```js
// src/logger.js
const pino = require('pino');

const transport = pino.transport({
  target: 'pino-opentelemetry-transport',
});

const logger = pino({ level: 'info' }, transport);
module.exports = logger;
```

Esse transport faz duas coisas:
1. Lê o contexto ativo do OTel (que o Init Container setou) e injeta `trace_id`/`span_id` na mensagem;
2. Envia os logs via **OTLP** diretamente para o Collector, além de escrever no stdout.

**Opção B — Hook manual (se não quiser dependência nova):**

```js
const { trace, context } = require('@opentelemetry/api');

function enrichWithTrace(obj) {
  const span = trace.getSpan(context.active());
  if (span) {
    const ctx = span.spanContext();
    return { ...obj, trace_id: ctx.traceId, span_id: ctx.spanId };
  }
  return obj;
}

logger.info(enrichWithTrace({ city: 'saopaulo' }), 'called');
```

A **Opção A** é mais limpa e não precisa de mudanças no ponto de chamada do log.

### 2.3 Não instalar SDK OTel

**NÃO** adicionar ao `package.json`:

```
# ❌ NÃO
@opentelemetry/sdk-node
@opentelemetry/auto-instrumentations-node
@opentelemetry/exporter-*
```

Essas libs vêm do **Init Container**. A única dependência OTel aceitável na app é
`@opentelemetry/api` (interfaces) se a squad emite métricas/spans customizadas.

---

## 3. Métricas customizadas (opcional)

```bash
npm install @opentelemetry/api
```

```js
// src/metrics.js
const { metrics } = require('@opentelemetry/api');

const meter = metrics.getMeter('weather.api');

const cityRequestsCounter = meter.createCounter('weather.city.requests', {
  description: 'Requests a /weather por cidade',
  unit: '1',
});

module.exports = { cityRequestsCounter };
```

```js
// uso
cityRequestsCounter.add(1, { city, env: process.env.ENV });
```

Mesmas regras de cardinalidade do guia Python. Nomes `<dominio>.<recurso>.<açao>`.

---

## 4. Pegadinhas (anti-patterns conhecidos)

### 4.1 `import` ESM antes do agente

A auto-instrumentação do Operator injeta `NODE_OPTIONS=--require @opentelemetry/auto-instrumentations-node/register`.
Isso funciona em CommonJS (`require`) pelo hook `--require`. Em **ESM**, `--require` roda antes, mas
alguns padrões de `import` dinâmico podem carregar libs instrumentadas antes dos hooks serem efetivos.

**Regra prática:** se a app usa ESM puro (`"type": "module"`), teste se os spans de libs como `pg` ou
`http` estão aparecendo. Se não, existe alternativa `--experimental-loader` ou voltar para CommonJS
para o arquivo de bootstrap.

### 4.2 Múltiplas instâncias do SDK

Se a imagem base da app já tem `@opentelemetry/sdk-node` (por exemplo, porque a squad copiou de
outra), o Init Container do Operator injeta uma **segunda** instância via `--require`. Resultado:
spans duplicados **ou** silêncio total.

Solução: remover toda dependência OTel do `package.json` (exceto `@opentelemetry/api`).

### 4.3 Healthchecks em traces

```yaml
# patch-instrumentation.yaml do overlay
spec:
  nodejs:
    env:
      - name: OTEL_NODE_ENABLED_INSTRUMENTATIONS
        value: "http,express,pg,pino"
      # ou excluir por URL (depende do framework)
      - name: OTEL_INSTRUMENTATION_HTTP_IGNORE_INCOMING_PATHS
        value: "/live,/ready,/healthz,/metrics"
```

### 4.4 Worker threads / cluster

A auto-instrumentação em workers exige que o `NODE_OPTIONS` seja herdado. Em geral funciona, mas
se a app faz `spawn` explícito de processos filhos, propagar `NODE_OPTIONS` manualmente.

---

## 5. `Deployment` mínimo (exemplo)

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: billing-api
spec:
  replicas: 1
  selector:
    matchLabels:
      app: billing-api
  template:
    metadata:
      labels:
        app: billing-api
        app_name: billing.api
        env: dev
      annotations:
        instrumentation.opentelemetry.io/inject-nodejs: "true"    # ← Node.js
    spec:
      containers:
        - name: billing-api
          image: registry.org/billing/billing-api:<tag>
          ports: [{ containerPort: 3000 }]
          env:
            - { name: APP_NAME, value: billing.api }
            - { name: ENV,      value: dev }
```

---

## 6. `Instrumentation` mínimo (exemplo)

```yaml
apiVersion: opentelemetry.io/v1alpha1
kind: Instrumentation
metadata:
  name: billing-instrumentation
spec:
  exporter:
    endpoint: http://otel-collector.observability.svc.cluster.local:4318
  propagators: [tracecontext, baggage]
  nodejs:
    env:
      - { name: OTEL_TRACES_EXPORTER,  value: otlp }
      - { name: OTEL_METRICS_EXPORTER, value: otlp }
      - { name: OTEL_LOGS_EXPORTER,    value: otlp }
      - { name: OTEL_NODE_ENABLED_INSTRUMENTATIONS, value: "http,express,pg,ioredis,pino" }
      - { name: OTEL_INSTRUMENTATION_HTTP_IGNORE_INCOMING_PATHS, value: "/live,/ready,/healthz,/metrics" }
      - { name: OTEL_SERVICE_NAME,     value: billing.api }
      - name: OTEL_RESOURCE_ATTRIBUTES
        value: "service.name=billing.api,deployment.environment=prod,application.name=billing.api"
```

---

## 7. Checklist por squad Node.js

- [ ] `package.json` **sem** `@opentelemetry/sdk-node`, `auto-instrumentations-node`, ou exporters
- [ ] `pino` (ou winston) configurado para emitir JSON no `stdout`
- [ ] `pino-opentelemetry-transport` (ou hook manual) para injetar `trace_id`/`span_id` nos logs
- [ ] `Deployment` com annotation `instrumentation.opentelemetry.io/inject-nodejs: "true"`
- [ ] Labels `app_name` e `env` alinhadas com os atributos OTel
- [ ] `Instrumentation` CR no mesmo namespace do Pod
- [ ] `OTEL_RESOURCE_ATTRIBUTES` com `service.name`, `deployment.environment`, `application.name` por overlay
- [ ] `OTEL_INSTRUMENTATION_HTTP_IGNORE_INCOMING_PATHS` configurado para excluir healthchecks
- [ ] Validação e2e (ver [`observability-playbook.md §9`](../observability-playbook.md#9-validação-end-to-end))

---

## 8. Referências

- OpenTelemetry JS — Contrib: <https://github.com/open-telemetry/opentelemetry-js-contrib>
- Pino OpenTelemetry transport: <https://github.com/pinojs/pino-opentelemetry-transport>
- Variáveis de ambiente OTel JS: <https://opentelemetry.io/docs/languages/js/configuration/>
