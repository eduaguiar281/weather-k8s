# Playbook de Observabilidade — Replicação Organizacional

> **Objetivo:** transformar a POC deste repositório em um **modelo replicável** por qualquer squad
> da organização, garantindo traces, métricas e logs **correlacionados**, com **zero ou mínima
> alteração de código de aplicação**, usando OpenTelemetry Operator + Auto-Instrumentation.

Este playbook cobre a arquitetura alvo, as responsabilidades entre Plataforma e Squad,
e o passo a passo operacional para que o modelo funcione em múltiplos clusters e múltiplas clouds.

Para o conceito técnico de **Init Container vs Sidecar**, leia [`instrumentation-patterns.md`](./instrumentation-patterns.md).
Para os detalhes específicos por stack, leia [`stacks/python.md`](./stacks/python.md) e [`stacks/nodejs.md`](./stacks/nodejs.md).

---

## Sumário

1. [Premissas](#1-premissas)
2. [Arquitetura alvo](#2-arquitetura-alvo)
3. [Modelo de repositórios (Azure DevOps)](#3-modelo-de-repositórios-azure-devops)
4. [Contrato de telemetria (padrões organizacionais)](#4-contrato-de-telemetria-padrões-organizacionais)
5. [Responsabilidades do time de Plataforma](#5-responsabilidades-do-time-de-plataforma)
6. [Responsabilidades da Squad](#6-responsabilidades-da-squad)
7. [Responsabilidades da Aplicação (dev)](#7-responsabilidades-da-aplicação-dev)
8. [Passo a passo do onboarding de uma nova aplicação](#8-passo-a-passo-do-onboarding-de-uma-nova-aplicação)
9. [Validação end-to-end](#9-validação-end-to-end)
10. [Troubleshooting organizacional](#10-troubleshooting-organizacional)
11. [Evolução e próximos passos](#11-evolução-e-próximos-passos)

---

## 1. Premissas

Este playbook **assume** que já existe na organização:

| Item | Situação assumida | Como a POC implementa |
|------|-------------------|------------------------|
| Cluster Kubernetes | 1+ clusters em produção em 2 clouds distintas | Cluster Kind local (`kind/cluster-config.yaml`) |
| ArgoCD | Instalado e operacional em cada cluster | Bootstrap via `scripts/02-bootstrap-kind-argocd.sh` |
| Grafana, Loki, Jaeger | Disponíveis (self-hosted ou gerenciados) por região | Via Docker Compose em `docker-compose.yml` |
| Promtail | Deployado como DaemonSet e ingestando em Loki | `k8s/infra/promtail/` (DaemonSet + ConfigMap + RBAC) |
| Registry de imagens | Autenticado no cluster | Usa `imagePullPolicy: Never` com imagens locais |
| Git | Azure DevOps | POC usa GitHub (conceito é o mesmo) |

O que **será entregue pela plataforma** (pode já existir parcialmente):

- OpenTelemetry Operator + cert-manager no cluster
- OpenTelemetry Collector regional por cluster/cloud
- Configuração do Promtail alinhada com o contrato de atributos OTel
- Provisioning de datasources Grafana e dashboards padrão
- Templates de `Instrumentation` CR por stack (Python, Node.js)
- ArgoCD ApplicationSet(s) que pegam manifests das squads

---

## 2. Arquitetura alvo

### 2.1 Visão geral (multi-cluster, 2 clouds)

```
  ┌───────────────────────────────────┐          ┌───────────────────────────────────┐
  │ CLOUD A — Cluster A               │          │ CLOUD B — Cluster B               │
  │                                   │          │                                   │
  │  namespace: squad-weather         │          │  namespace: squad-billing         │
  │  ┌─────────────────────────────┐  │          │  ┌─────────────────────────────┐  │
  │  │ Pod: weather-api            │  │          │  │ Pod: billing-api            │  │
  │  │  ┌──────────┐ ┌──────────┐  │  │          │  │  ┌──────────┐ ┌──────────┐  │  │
  │  │  │  INIT    │→│  APP     │  │  │          │  │  │  INIT    │→│  APP     │  │  │
  │  │  │  OTel    │ │ (Python) │  │  │          │  │  │  OTel    │ │ (Node)   │  │  │
  │  │  └──────────┘ └────┬─────┘  │  │          │  │  └──────────┘ └────┬─────┘  │  │
  │  └───────────────────┼─────────┘  │          │  └───────────────────┼─────────┘  │
  │                      │ OTLP       │          │                      │ OTLP       │
  │  namespace: observability          │          │  namespace: observability         │
  │  ┌───────────────────▼─────────┐  │          │  ┌───────────────────▼─────────┐  │
  │  │ OTel Collector (Deployment) │  │          │  │ OTel Collector (Deployment) │  │
  │  │ svc: otel-collector:4318    │  │          │  │ svc: otel-collector:4318    │  │
  │  └───┬─────────┬─────────┬─────┘  │          │  └───┬─────────┬─────────┬─────┘  │
  │      │         │         │        │          │      │         │         │        │
  │  namespace: monitoring              │          │  namespace: monitoring              │
  │  ┌───────────────────────────┐    │          │  ┌───────────────────────────┐    │
  │  │ Promtail DaemonSet         │    │          │  │ Promtail DaemonSet         │    │
  │  │ (lê /var/log/pods/*)       │    │          │  │ (lê /var/log/pods/*)       │    │
  │  └───────────────┬───────────┘    │          │  └───────────────┬───────────┘    │
  └──────────────────┼────────────────┘          └──────────────────┼────────────────┘
                     │                                              │
                     │ logs                                         │ logs
                     ▼                                              ▼
            ┌─────────────────────────────────────────────────────────────┐
            │  BACKENDS DE OBSERVABILIDADE  (gerenciados ou centralizados) │
            │                                                             │
            │   ┌─────────┐       ┌──────────┐       ┌────────────┐       │
            │   │ Jaeger  │       │   Loki   │       │ Prometheus │       │
            │   └────┬────┘       └─────┬────┘       └──────┬─────┘       │
            │        │                  │                   │             │
            │        └──────┬───────────┴───────────────────┘             │
            │               ▼                                             │
            │          ┌─────────┐                                        │
            │          │ Grafana │                                        │
            │          └─────────┘                                        │
            └─────────────────────────────────────────────────────────────┘
```

### 2.2 Decisões arquiteturais relevantes

| Decisão | Valor | Racional |
|---------|-------|----------|
| Instrumentação | **Init Container** (não Sidecar Collector) | Zero overhead contínuo por Pod; agente embarcado no processo da app. Ver [`instrumentation-patterns.md`](./instrumentation-patterns.md). |
| Collector | **1 Deployment por cluster** (namespace `observability`) | Balanceia custo x latência; cada app conversa com um endpoint curto: `otel-collector.observability.svc.cluster.local:4318`. |
| Coleta de logs | **Promtail DaemonSet** (já existente), **não** via OTLP do app | Reaproveita o que já temos; aplicação emite **JSON em stdout**, Promtail enriquece com labels e envia para Loki. |
| Propagação de contexto | **`tracecontext` + `baggage`** (W3C) | Padrão OTel; interoperável entre stacks. |
| Correlação log↔trace | **`OTEL_PYTHON_LOG_CORRELATION=true`** (e equivalentes) + logs JSON | `trace_id`/`span_id` viram campos indexáveis no Loki; `derivedFields` no Grafana gera link para Jaeger. |
| Cardinalidade | **Atributos de baixa cardinalidade** em labels/métricas (`service.name`, `deployment.environment`, `application.name`) | Protege Prometheus/Loki de explosão de séries. |

### 2.3 Por que dois Collectors (um por cloud)?

- **Isolamento regional:** falha em uma cloud não derruba telemetria da outra.
- **Latência:** app conversa com endpoint local (intra-cluster), sem sair da cloud.
- **Custo de saída (egress):** processamento/filtragem próximo da origem reduz dados cruzando clouds.
- **Política:** cada Collector pode ter config específica (sampling, redação de PII, exporters).

Os Collectors podem **federar** para um backend único (Jaeger/Prometheus/Loki central) ou para
backends regionais, conforme a decisão de residência de dados.

---

## 3. Modelo de repositórios (Azure DevOps)

O desenho abaixo reflete a topologia informada: time de plataforma central + squads
autônomas, aplicação **não conhece** os manifests.

```
Azure DevOps
├── Projeto: Platform
│   └── Repo: platform-observability
│       ├── clusters/<cloud>/<cluster>/
│       │   ├── otel-operator/                 # Operator + cert-manager
│       │   ├── otel-collector/                # Collector Deployment por cluster
│       │   ├── promtail/                      # DaemonSet + ConfigMap + RBAC
│       │   ├── grafana-provisioning/          # datasources, dashboards padrão
│       │   └── argocd/
│       │       ├── applicationsets/           # ApplicationSets para squads
│       │       └── apps/                      # Applications da infra
│       └── instrumentation-templates/         # templates por stack
│           ├── python/instrumentation.yaml
│           └── nodejs/instrumentation.yaml
│
├── Projeto: Squad-Weather
│   ├── Repo: weather-api                      # CÓDIGO DA APP
│   │   ├── Dockerfile
│   │   ├── main.py
│   │   └── requirements.txt
│   │
│   └── Repo: weather-manifests                # MANIFESTS DA SQUAD
│       └── apps/weather-api/
│           ├── base/
│           │   ├── namespace.yaml
│           │   ├── deployment.yaml            # com annotation inject-python
│           │   ├── service.yaml
│           │   └── instrumentation.yaml       # cópia do template + OTEL_SERVICE_NAME
│           └── overlays/
│               ├── dev/
│               │   ├── kustomization.yaml
│               │   ├── patch-deployment.yaml
│               │   └── patch-instrumentation.yaml
│               ├── hml/
│               └── prod/
│
└── Projeto: Squad-Billing
    ├── Repo: billing-api                      # CÓDIGO DA APP (Node.js)
    └── Repo: billing-manifests                # MANIFESTS DA SQUAD
```

### 3.1 Por que essa separação?

| Repo | Dono | Ciclo de vida | Rastreabilidade |
|------|------|---------------|-----------------|
| `platform-observability` | Plataforma | Mudanças raras, controladas por PR review obrigatório | Git log = histórico da infra |
| `<squad>-manifests` | Squad | Muda a cada release de qualquer app da squad | Separado do código; revisão de infra sem bloquear PRs de código |
| `<app>` (código) | Dev da squad | Muda constantemente | CI constrói imagem, **não altera manifests diretamente** |

### 3.2 Como a imagem chega nos manifests

Opções (escolher uma por organização):

1. **Tag pinned + PR automatizado**: pipeline da app gera PR no repo de manifests atualizando `image: registry/app:<sha>`. Recomendado para auditabilidade.
2. **ArgoCD Image Updater**: o Updater observa o registry e reescreve o manifest. Menor fricção, menos auditável.
3. **Helm values externos**: se o manifest usar Helm, um `values-override` com a tag é commitado pelo pipeline.

> A POC usa tag fixa `weather-api:local` + `kind load` local — serve como referência de
> **o que ir ao cluster**, mas no modelo organizacional o fluxo é via registry + tag.

---

## 4. Contrato de telemetria (padrões organizacionais)

Estes padrões **precisam ser acordados e documentados como standard**. Sem eles, dashboards,
alertas e consultas não são reutilizáveis entre squads.

### 4.1 Atributos de Resource (obrigatórios)

Toda aplicação deve emitir telemetria com pelo menos:

| Atributo | Formato | Exemplo | Onde é definido |
|----------|---------|---------|-----------------|
| `service.name` | `<domínio>.<serviço>`, lowercase, separado por `.` | `weather.api` | `OTEL_SERVICE_NAME` |
| `deployment.environment` | `dev` \| `hml` \| `prod` | `prod` | `OTEL_RESOURCE_ATTRIBUTES` |
| `application.name` | Igual a `service.name` (ou agrupador de BU) | `weather.api` | `OTEL_RESOURCE_ATTRIBUTES` |

Exemplo do valor final no Pod (formato que o Operator injeta):

```
OTEL_RESOURCE_ATTRIBUTES=service.name=weather.api,deployment.environment=prod,application.name=weather.api
```

> Veja na POC: `k8s/overlays/dev/patch-instrumentation.yaml` e `k8s/overlays/prod/patch-instrumentation.yaml`.
> O overlay muda **apenas** o valor de `deployment.environment` — o resto do CR vem do `base/`.

### 4.2 Labels no Kubernetes (alinhadas com os atributos OTel)

O `Deployment` deve carregar labels consistentes com os atributos OTel para que o Promtail
consiga correlacionar logs vindos de `stdout` com traces/métricas vindos do Collector.

```yaml
template:
  metadata:
    labels:
      app: weather-api            # selector interno (pode ter sufixo)
      app_name: weather.api       # == service.name OTel
      env: prod                   # == deployment.environment OTel
```

### 4.3 Formato de log (obrigatório)

- **JSON em `stdout`** — não texto livre. Sem JSON o `trace_id` acaba indexado como parte da
  mensagem em vez de campo estruturado, o que quebra as consultas no Loki.
- Campos mínimos: `asctime`, `level`, `message`, `service.name`.
- `trace_id`/`span_id` são injetados automaticamente pela auto-instrumentação quando
  `OTEL_<LANG>_LOG_CORRELATION=true` está setado.

### 4.4 Propagadores

```
propagators:
  - tracecontext    # W3C Trace Context (obrigatório)
  - baggage         # contexto adicional cruzando serviços
```

### 4.5 Nomenclatura de métricas customizadas

Se a squad quiser emitir métricas de negócio (exemplo na POC: `weather.city.requests`):

- `<dominio>.<recurso>.<açao>` — ex.: `weather.city.requests`, `billing.invoice.created`.
- **Unit** sempre definida (`1`, `ms`, `bytes`, ...).
- **Attributes** de baixa cardinalidade. **Nunca** usar IDs de usuário, request IDs, e-mails.

---

## 5. Responsabilidades do time de Plataforma

### 5.1 Instalar OpenTelemetry Operator + cert-manager (uma vez por cluster)

Referência da POC: `scripts/install-otel-operator.sh`.

```bash
# cert-manager (requisito do Operator)
kubectl apply --server-side --force-conflicts \
  -f https://github.com/cert-manager/cert-manager/releases/latest/download/cert-manager.yaml

# OpenTelemetry Operator
kubectl apply --server-side --force-conflicts \
  -f https://github.com/open-telemetry/opentelemetry-operator/releases/latest/download/opentelemetry-operator.yaml
```

No modelo organizacional, isso vira um `Application` do ArgoCD em `platform-observability/clusters/<cluster>/otel-operator/`.

> **Pegadinha conhecida (vimos na POC):** logo após instalar, o webhook do Operator pode
> retornar `connection refused` para os primeiros pods que nascem com a annotation de
> injeção. O ArgoCD resolve sozinho no próximo re-sync. O `scripts/04-apply-argocd-apps.sh`
> automatiza essa detecção/correção.

### 5.2 Deployar o OpenTelemetry Collector (um por cluster)

O Collector é o **ponto único de entrada** para telemetria de qualquer app do cluster. Deve
rodar no namespace `observability`, exposto como Service ClusterIP na porta `4318` (HTTP) e
opcionalmente `4317` (gRPC).

A configuração base é praticamente a da POC (`otel/otel-collector-config.yaml`), com
ajustes organizacionais:

```yaml
# platform-observability/clusters/<cluster>/otel-collector/configmap.yaml
receivers:
  otlp:
    protocols:
      grpc: { endpoint: 0.0.0.0:4317 }
      http: { endpoint: 0.0.0.0:4318 }

processors:
  memory_limiter:
    check_interval: 1s
    limit_mib: 1024            # ajustar conforme nó
    spike_limit_mib: 256

  batch:
    timeout: 1s
    send_batch_size: 1024

  # Promove atributos de resource a labels indexadas no Loki
  resource/loki_labels:
    attributes:
      - action: insert
        key: loki.resource.labels
        value: service.name, deployment.environment, application.name

  # (Opcional) Limite de cardinalidade em métricas
  metricstransform/cardinality_guard:
    transforms:
      - include: .*
        match_type: regexp
        action: update
        operations:
          - action: aggregate_labels
            label_set: [service.name, deployment.environment]
            aggregation_type: sum

exporters:
  otlp/jaeger:
    endpoint: jaeger.<REGIONAL_BACKEND>:4317
    tls: { insecure: false }

  prometheusremotewrite:                 # em org grande, prefira remote_write
    endpoint: https://prometheus.<REGIONAL_BACKEND>/api/v1/write
    resource_to_telemetry_conversion:
      enabled: true

  loki:
    endpoint: https://loki.<REGIONAL_BACKEND>/loki/api/v1/push
    default_labels_enabled: { exporter: true, job: true }

service:
  pipelines:
    traces:   { receivers: [otlp], processors: [memory_limiter, batch], exporters: [otlp/jaeger] }
    metrics:  { receivers: [otlp], processors: [memory_limiter, batch], exporters: [prometheusremotewrite] }
    logs:     { receivers: [otlp], processors: [memory_limiter, resource/loki_labels, batch], exporters: [loki] }
```

**Diferenças em relação à POC:**

| POC | Organização |
|-----|-------------|
| `exporter: prometheus` (scrape) | `prometheusremotewrite` (push) — mais natural cross-cluster |
| Collector atrás de Docker Compose com IP fixo `172.23.0.50` | Collector como Deployment K8s, Service ClusterIP |
| Endpoint na `Instrumentation`: `http://172.23.0.50:4318` | `http://otel-collector.observability.svc.cluster.local:4318` |

### 5.3 Manter o Promtail alinhado com o contrato OTel

O Promtail já existe na organização. Usando a config de `k8s/infra/promtail/configmap.yaml`
como ponto de partida, precisamos garantir que:

1. **Pipeline extrai labels** a partir do caminho `/var/log/pods/<ns>_<pod>_<uid>/<container>/*.log`.
2. **Deriva `env`** a partir do namespace (ou, melhor ainda, de uma label do pod — ver 5.3.1).
3. **Promove `service_name`, `app_name`, `deployment_environment`** como labels no Loki,
   com **o mesmo valor** dos atributos OTel. Assim queries funcionam entre logs e traces.

```yaml
# Trecho essencial (derivado de k8s/infra/promtail/configmap.yaml)
pipeline_stages:
  - cri: {}
  - regex:
      expression: '/var/log/pods/(?P<namespace>[^_]+)_(?P<pod>[^_]+)_[^/]+/(?P<container>[^/]+)/.*'
      source: filename
  - labels: { namespace:, pod:, container: }

  # Evolução organizacional: ler labels do pod via kubernetes_sd_configs,
  # em vez de derivar "env" do nome do namespace.
  - match:
      selector: '{namespace=~".+"}'
      stages:
        - template:
            source: app_name
            template: '{{ or .pod_label_app_name "unknown" }}'
        - labels: { app_name: }
        - template:
            source: deployment_environment
            template: '{{ or .pod_label_env "unknown" }}'
        - labels: { deployment_environment: }
```

#### 5.3.1 Evolução recomendada em relação à POC

A POC deriva `env` do **nome do namespace** (`weather-dev` → dev, `weather` → prod):

```yaml
# k8s/infra/promtail/configmap.yaml (trecho existente)
- template:
    source: env
    template: '{{ if eq .namespace "weather-dev" }}dev{{ else if eq .namespace "weather" }}prod{{ else }}{{ end }}'
```

Em escala organizacional isso **não escala**: cada squad teria que pedir alteração no
`ConfigMap` global. A evolução é:

- Cada Pod carrega labels `app_name`, `env` (ver [4.2](#42-labels-no-kubernetes-alinhadas-com-os-atributos-otel));
- Promtail usa `kubernetes_sd_configs` ou `discovery.kubernetes` para buscar labels do Pod;
- Pipeline promove essas labels sem nenhum condicional hardcoded.

Exemplo resumido:

```yaml
scrape_configs:
  - job_name: kubernetes-pods
    kubernetes_sd_configs: [{ role: pod }]
    relabel_configs:
      - source_labels: [__meta_kubernetes_pod_label_app_name]
        target_label: app_name
      - source_labels: [__meta_kubernetes_pod_label_env]
        target_label: env
      - source_labels: [__meta_kubernetes_namespace]
        target_label: namespace
      - source_labels: [__meta_kubernetes_pod_name]
        target_label: pod
      - action: replace
        source_labels: [__meta_kubernetes_pod_uid, __meta_kubernetes_pod_container_name]
        regex: (.+);(.+)
        replacement: /var/log/pods/${__meta_kubernetes_namespace}_${__meta_kubernetes_pod_name}_$1/$2/*.log
        target_label: __path__
```

> **Regra prática:** não mude o que o Promtail entrega para o Loki — mude **como ele
> chega nesse valor**. O label final `{app_name="weather.api", deployment_environment="prod"}`
> precisa continuar idêntico para que os dashboards existentes sigam funcionando.

### 5.4 Provisionar Grafana (datasources e dashboards padrão)

A POC já define o que precisa (`grafana/provisioning/datasources/datasources.yml`):

- **Prometheus** como datasource default
- **Loki** com `derivedFields` extraindo `trace_id` do corpo do log e linkando para Jaeger
- **Jaeger** com `tracesToLogsV2` gerando query Loki a partir do `trace.traceId`

O que muda na organização:

- URLs apontam para endpoints regionais (Grafana central ou por cloud);
- `customQuery` no `tracesToLogsV2` **deve usar o label padronizado**, não `namespace`/`container`:

```yaml
# Versão organizacional (genérica)
customQuery: true
query: '{service_name="$${__trace.service.name}", deployment_environment="$${__trace.tags.deployment_environment}"} |= "trace_id=$${__trace.traceId}"'
```

> Compare com a POC, onde estava `{namespace="weather", container="weather-api", log_source="app"}` —
> acopla ao nome do namespace. Em organização, use `service_name` + `deployment_environment`.

### 5.5 Templates de `Instrumentation` por stack

A plataforma mantém em `platform-observability/instrumentation-templates/`:

**Python:**
```yaml
# python/instrumentation.yaml  (template)
apiVersion: opentelemetry.io/v1alpha1
kind: Instrumentation
metadata:
  name: python-default-instrumentation    # a squad copia e renomeia
spec:
  exporter:
    endpoint: http://otel-collector.observability.svc.cluster.local:4318
  propagators: [tracecontext, baggage]
  resource:
    addK8sUIDAttributes: true
  python:
    env:
      - { name: OTEL_LOGS_EXPORTER,            value: otlp }
      - { name: OTEL_PYTHON_LOG_CORRELATION,   value: "true" }
      - { name: OTEL_METRICS_EXPORTER,         value: otlp }
      # OTEL_SERVICE_NAME e OTEL_RESOURCE_ATTRIBUTES são setados pela squad (overlay)
```

**Node.js:**
```yaml
# nodejs/instrumentation.yaml  (template)
apiVersion: opentelemetry.io/v1alpha1
kind: Instrumentation
metadata:
  name: nodejs-default-instrumentation
spec:
  exporter:
    endpoint: http://otel-collector.observability.svc.cluster.local:4318
  propagators: [tracecontext, baggage]
  resource:
    addK8sUIDAttributes: true
  nodejs:
    env:
      - { name: OTEL_LOGS_EXPORTER,     value: otlp }
      - { name: OTEL_METRICS_EXPORTER,  value: otlp }
      - { name: OTEL_TRACES_EXPORTER,   value: otlp }
      # Node.js auto-instrumentation correlaciona log→trace automaticamente
      # quando combinado com pino/winston + pino-opentelemetry-transport.
```

### 5.6 ApplicationSet do ArgoCD para squads

Evita criar `Application` manual para cada squad/app/env. A plataforma mantém um `ApplicationSet`
que gera automaticamente Applications baseado em diretórios ou em uma lista:

```yaml
# platform-observability/clusters/<cluster>/argocd/applicationsets/squads.yaml
apiVersion: argoproj.io/v1alpha1
kind: ApplicationSet
metadata:
  name: squads
  namespace: argocd
spec:
  generators:
    - matrix:
        generators:
          - list:
              elements:
                - squad: weather
                  repo: https://dev.azure.com/org/Squad-Weather/_git/weather-manifests
                - squad: billing
                  repo: https://dev.azure.com/org/Squad-Billing/_git/billing-manifests
          - list:
              elements:
                - env: dev
                - env: hml
                - env: prod
  template:
    metadata:
      name: '{{squad}}-{{env}}'
    spec:
      project: default
      source:
        repoURL: '{{repo}}'
        targetRevision: HEAD
        path: 'apps'
        directory:
          recurse: true
          include: '*/overlays/{{env}}/*'
      destination:
        server: https://kubernetes.default.svc
        namespace: 'squad-{{squad}}'
      syncPolicy:
        automated: { prune: true, selfHeal: true }
        syncOptions: [CreateNamespace=true]
```

> Na POC temos um Application por env (`weather-api-dev.yaml`, `weather-api-prod.yaml`).
> Em escala, isso vira ApplicationSet.

---

## 6. Responsabilidades da Squad

### 6.1 Estrutura mínima do repo de manifests

```
<squad>-manifests/
└── apps/
    └── <service>/
        ├── base/
        │   ├── namespace.yaml             # squad-<nome>
        │   ├── deployment.yaml            # com annotation inject-<lang>
        │   ├── service.yaml
        │   └── instrumentation.yaml       # cópia adaptada do template da plataforma
        └── overlays/
            ├── dev/
            │   ├── kustomization.yaml
            │   ├── patch-deployment.yaml          # replicas, resources
            │   ├── patch-instrumentation.yaml     # OTEL_RESOURCE_ATTRIBUTES
            │   └── secret.yaml
            ├── hml/
            └── prod/
```

Use o que já existe na POC como template: `k8s/base/` e `k8s/overlays/dev/`.

### 6.2 O Deployment obrigatório

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: weather-api
spec:
  replicas: 1
  selector: { matchLabels: { app: weather-api } }
  template:
    metadata:
      labels:
        app: weather-api
        app_name: weather.api            # alinhado com service.name OTel
        env: dev                         # sobrescrito pelo overlay
      annotations:
        instrumentation.opentelemetry.io/inject-python: "true"   # ← gatilho da injeção
    spec:
      containers:
        - name: weather-api
          image: registry.org/weather/weather-api:<tag>
          ports: [{ containerPort: 8000 }]
```

> **Única linha mágica:** `instrumentation.opentelemetry.io/inject-python: "true"`.
> Para Node.js: `instrumentation.opentelemetry.io/inject-nodejs: "true"`.
> Sem isso o Operator ignora o Pod.

### 6.3 A `Instrumentation` por aplicação

A squad **copia o template da plataforma** e altera apenas o nome e (se necessário) o
`OTEL_SERVICE_NAME`. O `OTEL_RESOURCE_ATTRIBUTES` fica no overlay.

```yaml
# base/instrumentation.yaml
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
      - { name: OTEL_LOGS_EXPORTER,          value: otlp }
      - { name: OTEL_PYTHON_LOG_CORRELATION, value: "true" }
      - { name: OTEL_SERVICE_NAME,           value: weather.api }
```

### 6.4 O patch por overlay (o que muda entre dev/hml/prod)

Reproduzindo o padrão da POC (`k8s/overlays/dev/patch-instrumentation.yaml`):

```yaml
# overlays/prod/patch-instrumentation.yaml
apiVersion: opentelemetry.io/v1alpha1
kind: Instrumentation
metadata:
  name: weather-instrumentation
spec:
  python:
    env:
      - name: OTEL_SERVICE_NAME
        value: weather.api
      - name: OTEL_RESOURCE_ATTRIBUTES
        value: "service.name=weather.api,deployment.environment=prod,application.name=weather.api"
```

E o `patch-deployment.yaml` troca label `env` para o valor do overlay:

```yaml
# overlays/prod/patch-deployment.yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: weather-api
spec:
  template:
    metadata:
      labels:
        env: prod
```

O `kustomization.yaml` do overlay costura tudo (igual à POC):

```yaml
apiVersion: kustomize.config.k8s.io/v1beta1
kind: Kustomization
namespace: squad-weather
resources:
  - ../../base
  - secret.yaml
patches:
  - path: patch-deployment.yaml
    target: { kind: Deployment,       name: weather-api }
  - path: patch-instrumentation.yaml
    target: { kind: Instrumentation,  name: weather-instrumentation }
```

---

## 7. Responsabilidades da Aplicação (dev)

A lista a seguir vale para **Python e Node.js**. Detalhes específicos nos guias por stack.

### 7.1 O que a aplicação DEVE fazer

- **Emitir logs em JSON no `stdout`**, com pelo menos `asctime`, `level`, `message`.
- **Respeitar nomes de endpoints de healthcheck** para que possam ser excluídos de traces (configurável via env).
- **Evitar anti-patterns** que desabilitam a auto-instrumentação (ver guia da stack).

### 7.2 O que a aplicação NÃO precisa fazer

- Importar/inicializar SDK do OpenTelemetry;
- Configurar exporters (endpoint, protocolo);
- Gerenciar propagadores ou tracers;
- Injetar `trace_id` manualmente no log.

Tudo isso é responsabilidade do **Init Container** + `Instrumentation` CR, injetados pelo Operator.

### 7.3 Exceção: métricas customizadas de negócio

Se a squad precisa emitir **métricas de negócio** (exemplo da POC: `weather.city.requests`),
a aplicação importa **apenas** `opentelemetry-api` (sem SDK):

```python
# Python — igual ao app/main.py da POC
from opentelemetry import metrics

_meter = metrics.get_meter("weather.api")
city_requests_counter = _meter.create_counter(
    name="weather.city.requests",
    description="Requests a /weather por cidade",
    unit="1",
)
city_requests_counter.add(1, {"city": city, "env": ENV})
```

O **SDK** vem do Init Container; o **API** vem do código. Isso mantém a aplicação
**agnóstica** (se um dia migrarmos do OTel, o código de métrica permanece trivialmente
substituível).

---

## 8. Passo a passo do onboarding de uma nova aplicação

Assumindo que a plataforma **já fez** o que está em [§5](#5-responsabilidades-do-time-de-plataforma).

### Dia 1 — Preparar o código

1. Garantir que os logs vão para `stdout` em formato JSON
   - Python: `python-json-logger` (ver `app/main.py`)
   - Node.js: `pino` com transport OTel (ver [`stacks/nodejs.md`](./stacks/nodejs.md))
2. Revisar anti-patterns da stack
   - Python + psycopg2: **não** usar `cursor_factory` diretamente no `cursor()`
   - Node.js: evitar `require`/`import` de libs instrumentadas **antes** do agente carregar (auto-instrumentação do Operator resolve via `--require`; mas `ESM` dinâmico pode burlar)
3. Gerar imagem Docker e publicar no registry

### Dia 2 — Configurar manifests da squad

4. Copiar `apps/<service>/` do template (ou de uma squad vizinha) para `<squad>-manifests`.
5. Ajustar em `base/`:
   - `namespace.yaml`: `squad-<nome>`
   - `deployment.yaml`: nome, imagem, labels (`app_name=<dominio>.<serviço>`)
   - `service.yaml`: porta
   - `instrumentation.yaml`: copiar do template da plataforma
6. Ajustar overlays `dev`/`hml`/`prod`:
   - `patch-deployment.yaml`: replicas, resources, label `env`
   - `patch-instrumentation.yaml`: `OTEL_RESOURCE_ATTRIBUTES` com env correto
7. Commit + push no repo de manifests da squad.

### Dia 3 — Sincronizar e validar

8. O ApplicationSet da plataforma detecta a nova app e cria os Applications.
9. Acompanhar pelo ArgoCD (`SYNC = Synced`, `HEALTH = Healthy`).
10. Validação e2e (próxima seção).

### Diagrama do fluxo

```
Dev                  Squad-manifests          Platform ArgoCD        Cluster
 │                         │                         │                  │
 │ 1. push código app      │                         │                  │
 ├────────────────────────►│ (CI gera imagem)        │                  │
 │                         │                         │                  │
 │  2. CI abre PR de bump  │                         │                  │
 │     de tag no manifest  │                         │                  │
 │                         │                         │                  │
 │  3. Merge no manifests  │                         │                  │
 │                         ├────────────────────────►│                  │
 │                         │  (ApplicationSet        │                  │
 │                         │    observa o repo)      │                  │
 │                         │                         ├─────────────────►│
 │                         │                         │  kubectl apply    │
 │                         │                         │                  ▼
 │                         │                         │            Operator injeta
 │                         │                         │            Init Container
 │                         │                         │            (ver próxima seção)
```

---

## 9. Validação end-to-end

Checklist obrigatório após cada onboarding. **Todos os itens precisam passar.**

### 9.1 Pod subiu com o Init Container

```bash
kubectl -n squad-weather describe pod -l app=weather-api | grep -A2 "Init Containers:"
```

Esperado:
```
Init Containers:
  opentelemetry-auto-instrumentation-python:
    Image: ghcr.io/open-telemetry/opentelemetry-operator/autoinstrumentation-python:<versão>
```

### 9.2 Env vars OTel estão injetadas

```bash
kubectl -n squad-weather exec deploy/weather-api -- env | grep OTEL_
```

Esperado pelo menos:
```
OTEL_SERVICE_NAME=weather.api
OTEL_RESOURCE_ATTRIBUTES=service.name=weather.api,deployment.environment=prod,...
OTEL_EXPORTER_OTLP_ENDPOINT=http://otel-collector.observability.svc.cluster.local:4318
OTEL_TRACES_EXPORTER=otlp
OTEL_METRICS_EXPORTER=otlp
OTEL_LOGS_EXPORTER=otlp
OTEL_PROPAGATORS=tracecontext,baggage
```

### 9.3 Trace aparece no Jaeger

Fazer uma requisição:
```bash
kubectl -n squad-weather port-forward svc/weather-api 8000:80 &
curl 'http://localhost:8000/weather?city=saopaulo'
```

No Jaeger UI, procurar por `Service: weather.api`. Esperado:
- `http.route=/weather`
- `http.status_code=200`
- Span filho `SELECT` (psycopg2) com `db.statement`, `db.system=postgresql`

### 9.4 Log no Loki correlacionado

No Grafana → Explore → datasource Loki:
```logql
{service_name="weather.api", deployment_environment="prod"} | json | line_format "{{.message}} trace={{.trace_id}}"
```

Esperado: logs com `trace_id` igual ao do span do Jaeger.

No painel do log, o campo `TraceID` deve aparecer como **link clicável** para Jaeger
(derivedField em `grafana/provisioning/datasources/datasources.yml`).

### 9.5 Métrica no Prometheus

```promql
sum by (city) (rate(weather_city_requests_total{deployment_environment="prod"}[5m]))
```

Esperado: série temporal com pelo menos uma label `city` preenchida.

### 9.6 Link trace → logs funciona

No Jaeger, abrir um trace → botão "Logs for this span" → deve levar para Loki com o
`trace_id` já filtrado via `customQuery` do datasource.

---

## 10. Troubleshooting organizacional

Problemas recorrentes vistos na POC (e que se manifestam igual em produção):

### 10.1 Pod sobe sem o Init Container

- **Causa 1:** annotation `instrumentation.opentelemetry.io/inject-python: "true"` ausente ou em lugar errado (precisa ser em `spec.template.metadata.annotations`, não em `metadata.annotations` do Deployment).
- **Causa 2:** `Instrumentation` CR não está no mesmo namespace do Pod.
- **Causa 3:** Webhook do Operator não pronto ainda (`connection refused`). Re-sync Application; ou reaplicar `Deployment`.

### 10.2 Trace aparece, mas sem span SQL (psycopg2)

Cenário visto na POC:
```python
cur = conn.cursor(cursor_factory=RealDictCursor)  # ❌ sobrescreve o TracedCursorFactory
```

Solução: `cur = conn.cursor()` e converter tuplas em dict via `cursor.description` (ver `app/main.py`).

### 10.3 Log não tem `trace_id`

- **Causa 1:** log não está em JSON. `OTEL_PYTHON_LOG_CORRELATION` injeta o trace_id, mas em texto livre o Loki não estrutura o campo. Mudar para JSON formatter.
- **Causa 2:** `OTEL_PYTHON_LOG_CORRELATION=true` ausente da `Instrumentation`.

### 10.4 Label `deployment_environment` não aparece no Loki

- **Causa:** o Promtail não está promovendo o label OU a app não está com `OTEL_RESOURCE_ATTRIBUTES` correto.
- Conferir:
  - `kubectl exec` e verificar a env var;
  - Pipeline Promtail — seção "Alinha labels com resource OTel" em `k8s/infra/promtail/configmap.yaml`.
- Na evolução para `kubernetes_sd_configs`, verificar que o Pod tem a label `env`.

### 10.5 Applications fora de sync após deploy do Operator

Detalhado na POC (`README.md` seção Troubleshooting). O script `scripts/04-apply-argocd-apps.sh`
detecta e corrige o caso do webhook. No modelo organizacional, o ArgoCD tende a se auto-corrigir
com `selfHeal: true`, mas configurar um `retry` explícito é recomendado:

```yaml
syncPolicy:
  automated: { prune: true, selfHeal: true }
  retry:
    limit: 5
    backoff: { duration: 10s, factor: 2, maxDuration: 5m }
```

### 10.6 Collector recebe tudo, mas Jaeger não mostra spans

- Verificar config do exporter `otlp/jaeger` no Collector — endpoint e TLS.
- Checar logs do Collector: `kubectl -n observability logs deploy/otel-collector`.
- Se `debug: verbosity: basic` estiver ligado, os spans aparecem no log do Collector antes de sair.

---

## 11. Evolução e próximos passos

Lista priorizada de melhorias que o time de plataforma pode adotar em sequência:

| # | Tópico | Por quê |
|---|--------|---------|
| 1 | **Migrar Promtail para Grafana Alloy** | Promtail está em modo de manutenção. Alloy consolida Promtail + OTel em um único agente e suporta pipelines OTLP nativos. |
| 2 | **Substituir Jaeger por Grafana Tempo** | Tempo integra nativamente com Loki/Prometheus/Grafana e tem melhor storage eficiente. |
| 3 | **Sampling policy no Collector** | `tail_sampling` processor: amostra 100% de erros + 10% do resto. Reduz custo mantendo observabilidade de falhas. |
| 4 | **Cardinality guards** | `metricstransform` + limites em `prometheusremotewrite`. Evita que uma squad derrube o TSDB. |
| 5 | **Redação de PII** | `attributesprocessor` removendo headers/queries sensíveis antes de exportar. |
| 6 | **SLO/SLI dashboards padrão** | Um dashboard Grafana "SLO por serviço" que lê `service.name` e `deployment.environment` e não precisa ser duplicado por squad. |
| 7 | **Alertmanager integrado ao Loki (log-based alerts)** | Alertas como "spike de `level=ERROR`" direto do Loki, sem métrica intermediária. |
| 8 | **Mais stacks** | Java (`inject-java`), .NET (`inject-dotnet`), Go (requer **Sidecar** — ver [`instrumentation-patterns.md`](./instrumentation-patterns.md)). |

---

## Apêndice A — Mapa "POC → Organização"

Referência rápida de onde cada conceito da POC aparece no modelo organizacional.

| POC (este repo) | Organização |
|-----------------|-------------|
| `docker-compose.yml` (Jaeger, Loki, Prometheus, Grafana) | Managed services ou stack central em `platform-observability` |
| `otel/otel-collector-config.yaml` | `platform-observability/clusters/<cluster>/otel-collector/configmap.yaml` |
| `k8s/infra/promtail/*` | Idem, já existe no repo da plataforma; evoluir para usar `kubernetes_sd_configs` |
| `k8s/base/instrumentation.yaml` | `platform-observability/instrumentation-templates/python/instrumentation.yaml` (template) + `<squad>-manifests/apps/<svc>/base/instrumentation.yaml` (cópia) |
| `k8s/base/deployment.yaml` (annotation inject) | `<squad>-manifests/apps/<svc>/base/deployment.yaml` |
| `k8s/overlays/{dev,prod}/patch-instrumentation.yaml` | `<squad>-manifests/apps/<svc>/overlays/{dev,hml,prod}/patch-instrumentation.yaml` |
| `k8s/argocd/weather-api-{dev,prod}.yaml` (1 Application por env) | ApplicationSet em `platform-observability/clusters/<cluster>/argocd/applicationsets/squads.yaml` |
| `grafana/provisioning/datasources/datasources.yml` | Idem, em `platform-observability/clusters/<cluster>/grafana-provisioning/datasources.yml` — URLs regionais e `customQuery` genérico |
| `scripts/install-otel-operator.sh` | Application ArgoCD em `platform-observability/clusters/<cluster>/otel-operator/` |
| `scripts/load-test.sh` | Útil como job de validação pós-deploy (CronJob ou pipeline) |

## Apêndice B — Por que esses padrões e não outros

- **Auto-instrumentação via Operator vs SDK no código:** a POC demonstra que a primeira
  entrega ~90% do valor com ~2 linhas de código (log JSON + psycopg2 cursor). Em uma
  organização com dezenas de squads, padronizar via infra é ordens de magnitude mais
  escalável.
- **Init Container vs Sidecar Collector:** escolhemos Init por eficiência de recursos;
  reservamos Sidecar para casos que demandam enriquecimento/buffering por Pod ou stacks
  que não rodam in-process (Go, binários compilados). Ver [`instrumentation-patterns.md`](./instrumentation-patterns.md).
- **Promtail vs OTLP logs no app:** reaproveitamos o que já está instalado e permite que
  aplicações emitam logs sem depender de rede para telemetria (stdout é sempre confiável).
  No longo prazo, Alloy substitui Promtail sem mudar contrato.
- **Collector por cluster vs DaemonSet vs externo:** Deployment oferece a melhor relação
  custo/complexidade para a maioria dos casos; DaemonSet vira necessário em cargas muito
  altas por nó. Externo ao cluster (como na POC) não escala para múltiplas clouds.
