# Padrões de Instrumentação: Init Container vs Sidecar Container

Este documento explica **por que usamos Init Container** no modelo organizacional e
**quando Sidecar é a escolha correta**. É complementar ao [`observability-playbook.md`](./observability-playbook.md)
e à documentação histórica da POC em [`observability-sidecar-pattern.md`](./observability-sidecar-pattern.md).

> **Nota terminológica.** O nome do arquivo histórico é `observability-sidecar-pattern.md`,
> mas o conteúdo descreve **Init Container** (Auto-Instrumentation via Operator). Mantido
> por rastreabilidade histórica. Este documento aqui é a referência canônica de conceito.

---

## Sumário

1. [Fundamentos: o que é cada um no Kubernetes](#1-fundamentos-o-que-é-cada-um-no-kubernetes)
2. [Init Container no contexto OpenTelemetry](#2-init-container-no-contexto-opentelemetry)
3. [Sidecar Container no contexto OpenTelemetry](#3-sidecar-container-no-contexto-opentelemetry)
4. [Tabela comparativa](#4-tabela-comparativa)
5. [Quando usar cada um](#5-quando-usar-cada-um)
6. [Quando combinar os dois](#6-quando-combinar-os-dois)
7. [Decisão na organização](#7-decisão-na-organização)

---

## 1. Fundamentos: o que é cada um no Kubernetes

Antes do contexto OpenTelemetry, vale firmar os conceitos gerais do Kubernetes.

### 1.1 Init Container

Um **Init Container** é um container que **roda até a conclusão** _antes_ que os containers principais do Pod iniciem.

Características:

- Executa **sequencialmente** (`initContainers[0]` → `initContainers[1]` → ... → containers principais).
- Se qualquer Init falhar, o Pod é reiniciado (respeitando `restartPolicy`).
- **Não faz parte do ciclo de vida de execução do Pod:** depois que termina, não ocupa mais CPU/RAM.
- Compartilha **volumes** e **network namespace** com os containers principais.
- Serve para: preparar dados, baixar artefatos, rodar migrations, esperar dependências externas.

### 1.2 Sidecar Container

Um **Sidecar Container** é um container que **roda durante toda a vida do Pod**, lado a lado com o container principal, compartilhando network namespace e (opcionalmente) volumes.

Características:

- Começa junto com os containers principais e **termina junto**.
- Ocupa CPU/RAM **o tempo todo**.
- Falha do Sidecar **não mata o container principal** (mas pode degradar o que ele fornece).
- Serve para: proxy (Envoy/Istio), log shipper, cache local, **OTel Collector por Pod**.

> Em versões recentes do Kubernetes (1.28+) existe a formalização via `initContainers[].restartPolicy: Always`
> — um "sidecar nativo" que o Kubernetes gerencia como init mas mantém ligado. Por ora, trate
> "sidecar" como um container comum dentro do Pod, iniciando com a app.

### 1.3 Resumo visual

```
Pod lifecycle

 t=0   ┌──────────────────────────────────────────────────────────┐
       │                                                          │
       │  Init Container (roda uma vez, termina)                  │
       │  ┌────────────────────┐                                  │
       │  │  cp libs para vol  │   CPU/RAM: pico → 0              │
       │  └──────┬─────────────┘                                  │
       │         │                                                 │
 t=1   │         ▼ (termina)                                       │
       │                                                          │
       │  App Container + Sidecar Container  (rodam juntos)       │
       │  ┌───────────────┐     ┌──────────────────┐              │
       │  │     App       │◄───►│   Sidecar        │   CPU/RAM:   │
       │  │ (Python/Node) │     │  (Collector)     │   contínuo   │
       │  └───────────────┘     └──────────────────┘              │
       │                                                          │
 t=∞   │  (ambos terminam quando o Pod termina)                   │
       └──────────────────────────────────────────────────────────┘
```

---

## 2. Init Container no contexto OpenTelemetry

### 2.1 O que é

Quando o **OpenTelemetry Operator** detecta em um Pod a annotation
`instrumentation.opentelemetry.io/inject-<lang>: "true"`, ele **injeta** um Init Container
padrão chamado `opentelemetry-auto-instrumentation-<lang>`, que:

1. Roda a imagem `ghcr.io/open-telemetry/opentelemetry-operator/autoinstrumentation-<lang>`;
2. Executa `cp -r /autoinstrumentation/. /otel-auto-instrumentation-<lang>`, copiando as libs OTel para um **volume compartilhado** (`emptyDir`);
3. Termina.

O container da aplicação inicia **depois**, com:

- O mesmo volume montado em `/otel-auto-instrumentation-<lang>`;
- Variáveis de ambiente injetadas pelo Operator:
  - `PYTHONPATH` (Python) / `NODE_OPTIONS` (Node.js) / `JAVA_TOOL_OPTIONS` (Java) apontando para o volume;
  - `OTEL_*` com exporter, endpoint, propagadores, service name, etc.

Quando a app arranca, o runtime **carrega o agente OTel no mesmo processo** antes do código
da aplicação. O agente faz **monkey-patching** em libs conhecidas (FastAPI, psycopg2, http,
express, pg, etc.) e passa a gerar spans/métricas automaticamente.

### 2.2 Arquitetura (trecho relevante)

```
┌──── Pod ─────────────────────────────────────────────────────────────┐
│                                                                      │
│  emptyDir: otel-auto-instrumentation-python  (volume compartilhado)  │
│            ▲                                   │                     │
│            │ cp -r                             │ mount                │
│  ┌─────────┴───────────┐            ┌──────────▼──────────┐          │
│  │  Init Container     │            │  App Container      │          │
│  │  autoinstr-python   │   (sobe)   │  weather-api        │          │
│  │  (terminou no t=1)  │ ─────────► │                     │          │
│  └─────────────────────┘            │  PYTHONPATH=/otel-… │          │
│                                     │  ├── sitecustomize  │          │
│                                     │  │   (hooks OTel)   │          │
│                                     │  └── app code       │          │
│                                     │                     │          │
│                                     │  OTLP HTTP ────────►│───┐      │
│                                     └─────────────────────┘   │      │
└───────────────────────────────────────────────────────────────┼──────┘
                                                                │
                                                                ▼
                                   otel-collector.observability.svc.cluster.local:4318
```

### 2.3 O que é gerado automaticamente pelo Operator

O trecho abaixo é **gerado em runtime pelo Operator** quando ele admite o Pod — você não
escreve isso nos seus manifests:

```yaml
initContainers:
  - name: opentelemetry-auto-instrumentation-python
    image: ghcr.io/open-telemetry/opentelemetry-operator/autoinstrumentation-python:0.60b1
    command: ["cp", "-r", "/autoinstrumentation/.", "/otel-auto-instrumentation-python"]
    volumeMounts:
      - { name: opentelemetry-auto-instrumentation-python, mountPath: /otel-auto-instrumentation-python }

containers:
  - name: weather-api
    env:
      - name: PYTHONPATH
        value: /otel-auto-instrumentation-python/opentelemetry/instrumentation/auto_instrumentation:/otel-auto-instrumentation-python
      - name: OTEL_TRACES_EXPORTER
        value: otlp
      - name: OTEL_METRICS_EXPORTER
        value: otlp
      - name: OTEL_LOGS_EXPORTER
        value: otlp
      - name: OTEL_EXPORTER_OTLP_ENDPOINT
        value: http://otel-collector.observability.svc.cluster.local:4318
      - name: OTEL_EXPORTER_OTLP_PROTOCOL
        value: http/protobuf
      - name: OTEL_SERVICE_NAME
        value: weather.api
      - name: OTEL_PROPAGATORS
        value: tracecontext,baggage
      - name: OTEL_PYTHON_LOG_CORRELATION
        value: "true"
    volumeMounts:
      - { name: opentelemetry-auto-instrumentation-python, mountPath: /otel-auto-instrumentation-python }

volumes:
  - { name: opentelemetry-auto-instrumentation-python, emptyDir: {} }
```

### 2.4 Vantagens

- **Zero overhead contínuo:** depois do init, só a app roda (mais o código OTel dentro do mesmo processo, que é fino);
- **Alta fidelidade:** o agente enxerga internals da app (cliente HTTP, DBAPI, ORM) — gera spans profundos;
- **Zero mudança de código** (exceto o indispensável: log JSON e evitar anti-patterns da stack);
- **Configuração via infra** (CRD + env vars), desacoplada da imagem da app;
- **Simples de manter:** o Operator versiona a imagem do agente; upgrade vem via ArgoCD.

### 2.5 Limitações

- **Requer runtime com mecanismo de injeção in-process**: Python (`PYTHONPATH`), Node.js (`NODE_OPTIONS=--require`), Java (`-javaagent`), .NET (profiler API). **Go não suporta** — binário estaticamente compilado sem runtime hooks.
- **Algumas libs precisam patterns específicos** para não burlar o monkey-patching (ver seção "Pegadinhas" nos guias por stack).
- **Sem controle direto no app** sobre sampling, redactions etc. — precisa fluir pelo Collector.
- **Acoplado ao ciclo de startup da app**: um erro no agente atrasa o arranque.

---

## 3. Sidecar Container no contexto OpenTelemetry

### 3.1 O que é

Um Sidecar no contexto OTel é um **OpenTelemetry Collector rodando dentro do Pod**, ao lado
da aplicação. A app envia telemetria para `localhost:4318` (ou `4317`), e o Collector
sidecar faz o processamento/roteamento.

O Operator pode injetar isso automaticamente via CRD `OpenTelemetryCollector` com
`spec.mode: sidecar` + annotation `sidecar.opentelemetry.io/inject: "<nome-do-collector>"`:

```yaml
apiVersion: opentelemetry.io/v1beta1
kind: OpenTelemetryCollector
metadata:
  name: sidecar-billing
  namespace: squad-billing
spec:
  mode: sidecar
  config: |
    receivers:
      otlp:
        protocols: { http: {endpoint: 0.0.0.0:4318}, grpc: {endpoint: 0.0.0.0:4317} }
    processors:
      batch: {}
      attributes/pii_scrub:
        actions:
          - key: http.request.header.authorization
            action: delete
    exporters:
      otlp:
        endpoint: otel-collector.observability.svc.cluster.local:4317
        tls: { insecure: true }
    service:
      pipelines:
        traces:  { receivers: [otlp], processors: [attributes/pii_scrub, batch], exporters: [otlp] }
        metrics: { receivers: [otlp], processors: [batch], exporters: [otlp] }
        logs:    { receivers: [otlp], processors: [batch], exporters: [otlp] }
```

E no Deployment da app:
```yaml
metadata:
  annotations:
    sidecar.opentelemetry.io/inject: "sidecar-billing"
```

### 3.2 Arquitetura

```
┌──── Pod ──────────────────────────────────────────────────────────┐
│                                                                   │
│  ┌─────────────────────┐      localhost:4318    ┌───────────────┐ │
│  │  App Container      │ ────────────────────►  │  Sidecar       │ │
│  │  (emite OTLP)       │                        │  OTel Collector│ │
│  │                     │                        │                │ │
│  └─────────────────────┘                        │  processors    │ │
│                                                 │  (scrub, batch)│ │
│                                                 │                │ │
│                                                 └──────┬─────────┘ │
└────────────────────────────────────────────────────────┼───────────┘
                                                         │ OTLP gRPC
                                                         ▼
                                     otel-collector-gateway.observability:4317
                                              (Collector central)
```

### 3.3 Vantagens

- **Enriquecimento/filtragem próximos da app:** scrub de PII, atributos estáticos, sampling local;
- **Buffering resiliente:** se o Collector central cai, o sidecar segura dados;
- **Tenancy forte:** cada Pod com política própria (ex.: squad X faz head sampling 10%, squad Y 100%);
- **Suporta stacks sem auto-instrumentação in-process** (Go, C++, Rust), onde o app emite OTLP manualmente e o sidecar roteia;
- **Config por-app**, versionada junto com o manifest da squad.

### 3.4 Desvantagens

- **Overhead por Pod:** 50–150 MB RAM + 0.05–0.2 vCPU dedicados para o Collector. Em cluster com milhares de Pods, vira bilhões de bytes de memória reservada.
- **Complexidade operacional:** configuração por-app em YAML; upgrades do Collector distribuídos;
- **Ainda não instrumenta a app sozinho:** precisa de Init (ou SDK manual) para o app emitir OTLP no `localhost`;
- **Ponto extra de falha:** se o sidecar morre, a app envia para `localhost:4318` que não responde — o SDK OTel lida bem (buffers com retry), mas ainda é uma dependência adicional.

---

## 4. Tabela comparativa

| Aspecto | **Init Container (auto-instrumentação)** | **Sidecar Container (Collector per Pod)** |
|---------|-------------------------------------------|---------------------------------------------|
| Papel | Injetar **agente OTel** no processo da app | Rodar um **Collector dedicado** ao Pod |
| Ciclo de vida | Executa uma vez e **termina** | Vive enquanto o Pod viver |
| Overhead em runtime | Quase zero (código no mesmo processo) | ~50–150 MB RAM + CPU dedicado, por Pod |
| Responsabilidade | Gerar telemetria a partir de libs instrumentadas | Receber/processar/rotear telemetria |
| Mudanças na app | Nenhuma (ou mínimas: log JSON) | Nenhuma, mas a app aponta para `localhost` |
| Suporte por linguagem | Python, Node.js, Java, .NET, Ruby (PHP em experimental) | Qualquer linguagem — basta emitir OTLP |
| Propagação de contexto | Automática (libs instrumentadas) | A cargo da app/SDK |
| Falha do componente | App **não sobe** se Init falhar | App sobe, mas perde telemetria (com retry) |
| Upgrade do componente | Rolling restart do Pod puxa nova imagem do agente | Reiniciar Pod puxa nova config do sidecar |
| Configuração | CRD `Instrumentation` (centralizada) | CRD `OpenTelemetryCollector` mode `sidecar` (por-squad) |
| Quando escalar | Ótimo para dezenas/centenas de serviços com padrão único | Ideal quando cada serviço precisa de tratamento diferente |

---

## 5. Quando usar cada um

### 5.1 Use Init Container quando

- A stack da app é **suportada pela auto-instrumentação** (Python, Node.js, Java, .NET, Ruby).
- O comportamento desejado de telemetria é **homogêneo na organização** (mesmos exporters, mesmos propagadores, sampling central).
- **Overhead por Pod importa** (muitos Pods por nó).
- Você quer entregar **observabilidade sem exigir nada** do dev além de logs em JSON.

**Esta é a escolha do modelo organizacional deste playbook.**

### 5.2 Use Sidecar Collector quando

- Stack da app **não tem agente in-process** (Go, Rust, C++): a app emite OTLP via SDK → sidecar recebe em `localhost`.
- A squad/app tem **requisitos de processamento específicos** (PII scrubbing com chaves próprias, sampling custom, routing multi-backend).
- A app vive em uma rede segregada e **não deve** falar direto com o Collector central (sidecar faz a ponte).
- Resiliência extra é obrigatória (buffer local + retry).

### 5.3 Use SDK direto no código quando

- A telemetria precisa de **spans/attributes customizados muito finos** que a auto-instrumentação não gera.
- A app é uma **biblioteca distribuída** que empacota seu próprio SDK (ex.: SaaS que vende observabilidade como feature).
- Estamos em uma fase de experimentação rápida antes de decidir o modelo organizacional.

---

## 6. Quando combinar os dois

Cenário real em organizações maduras:

```
┌── Pod ──────────────────────────────────────────────────────────────┐
│                                                                     │
│  ┌─ Init Container ──┐                                              │
│  │ copia agente OTel │ (termina)                                    │
│  └───────┬───────────┘                                              │
│          ▼                                                          │
│  ┌─ App Container ────┐  localhost:4318   ┌─ Sidecar Collector ─┐  │
│  │ Python/Node + OTel │ ────────────────► │ filter + scrub      │  │
│  │ agente (in-process)│                   │ + batch             │  │
│  └────────────────────┘                   └───────┬─────────────┘  │
│                                                    │               │
└────────────────────────────────────────────────────┼───────────────┘
                                                    │ OTLP gRPC
                                                    ▼
                                      Gateway Collector (cluster)
```

**Padrão "agente + sidecar":**

- **Init** faz a auto-instrumentação **do processo** (spans profundos, zero código);
- **Sidecar** faz o **processamento local** (enrichment, redação de PII, buffer) antes de sair do Pod;
- **Collector central (gateway)** concentra as saídas cross-cluster.

Esse combo vale o custo quando:
- Requisitos regulatórios obrigam scrub local (dados nunca saem do Pod com PII);
- Múltiplos backends com routing por atributo;
- Picos de tráfego onde buffer local absorve latência do gateway.

---

## 7. Decisão na organização

| Cenário | Decisão |
|---------|---------|
| Aplicações Python/Node.js/Java/.NET — **maioria** | **Init Container** apenas. Gateway Collector por cluster. |
| Aplicações Go | **Sidecar Collector** + SDK OTel manual no código Go. Sem Init (não se aplica). |
| Apps com PII sensível obrigada a ficar no Pod | **Init + Sidecar** com processor de redação no sidecar. |
| POCs e experimentos | **Init Container** é suficiente, seguindo os templates da plataforma. |

> Na POC deste repositório usamos **apenas Init Container** (a aplicação é Python). Nenhum
> Sidecar está presente. O nome do arquivo `observability-sidecar-pattern.md` é um
> "falso amigo" herdado e foi mantido por motivos históricos.

---

## Referências

- OpenTelemetry Operator: <https://github.com/open-telemetry/opentelemetry-operator>
- CRD `Instrumentation`: <https://github.com/open-telemetry/opentelemetry-operator/blob/main/docs/api/instrumentations.md>
- CRD `OpenTelemetryCollector`: <https://github.com/open-telemetry/opentelemetry-operator/blob/main/docs/api/opentelemetrycollectors.md>
- Kubernetes Sidecar Containers (native): <https://kubernetes.io/docs/concepts/workloads/pods/sidecar-containers/>
