# weather-k8s

Stack de exemplo com API de clima, manifests Kubernetes (Kustomize), observabilidade via Docker Compose e GitOps com **Kind** (Kubernetes in Docker) e **Argo CD**.

Este documento cobre o ambiente local desde o zero: cluster Kind, instalação do Argo CD e notas para **macOS** e **Linux (incluindo WSL2)** sem depender de caminhos ou ferramentas específicos de uma única plataforma.

---

## Pré-requisitos

| Ferramenta | Função |
|------------|--------|
| [Docker](https://docs.docker.com/get-docker/) | Motor de containers usado pelo Kind |
| [Kind](https://kind.sigs.k8s.io/docs/user/quick-start/#installation) | Cria o cluster Kubernetes local |
| [kubectl](https://kubernetes.io/docs/tasks/tools/) | CLI do Kubernetes |

**Regra geral:** use os binários no `PATH` e o mesmo contexto `kubectl` que o Kind configurar (`kind-local` quando o cluster se chama `local`). Os scripts do repositório assumem o cluster **`local`**.

### macOS

```bash
brew install kind kubectl
```

O Docker Desktop para Mac atende ao requisito do daemon Docker.

### Linux (nativo)

```bash
# Exemplo Debian/Ubuntu — ajuste conforme a distribuição
sudo apt-get update && sudo apt-get install -y kubectl
# Kind: siga https://kind.sigs.k8s.io/docs/user/quick-start/#installation
```

### Windows Subsystem for Linux (WSL2)

- **Docker Desktop com integração WSL2:** instale o Docker Desktop no Windows, ative a integração com sua distro WSL e use `docker` e `kubectl` *dentro do WSL*. O Kind funciona normalmente.
- **Docker Engine só no WSL:** também é suportado; mantenha o serviço `docker` em execução antes de rodar o Kind.

Evite misturar `kubectl` do Windows com o cluster criado no WSL: sempre use o `kubectl` do mesmo ambiente em que o Kind foi executado.

---

## Passo a passo completo (ordem obrigatória)

Siga nesta ordem. Em cada etapa, só avance se o "verificar" estiver ok.

### 1. Ferramentas e Docker

Instale **Docker**, **kind** e **kubectl** e confirme:

```bash
docker info
kind version
kubectl version --client
```

### 2. Commit e push no GitHub (obrigatório antes do passo 5)

O Argo CD **clona o repositório remoto** (`repoURL` em `k8s/argocd/*.yaml`), não o seu diretório local. Mudanças que não estiverem no GitHub não entram no sync.

- Faça **commit e push** do branch que você usa (ex.: `main`) para `origin` antes de prosseguir.

### 3. Rede Docker + stack de observabilidade

```bash
./scripts/01-ensure-observability-network.sh
docker compose up -d
```

Verificar: `docker compose ps` — todos os serviços em `Up`.

Se aparecer *network declared as external, but could not be found*: rode `./scripts/01-ensure-observability-network.sh` e tente de novo.

### 4. Cluster Kind + cert-manager + OpenTelemetry Operator + Argo CD

```bash
./scripts/02-bootstrap-kind-argocd.sh
kubectl config use-context kind-local
kubectl get pods -n argocd
```

O script instala em sequência, aguardando cada etapa: **Kind → cert-manager → OpenTelemetry Operator → Argo CD**. Se algum componente já existir, pula automaticamente.

Verificar: pods do namespace `argocd` em `Running` (pode levar ~5 min na primeira vez).

> **Nota sobre versões:** por padrão aplica o manifest `stable` do Argo CD. Para fixar uma versão:
> ```bash
> ARGOCD_VERSION=v2.13.4 ./scripts/02-bootstrap-kind-argocd.sh
> ```

### 5. Credencial SSH do GitHub no Argo CD

> **Apenas se `repoURL` nos YAML usar `git@github.com:...` (SSH).** Para repos públicos com HTTPS, pule este passo.

**5.1 — Gerar par de chaves dedicado** (sem passphrase):

```bash
ssh-keygen -t ed25519 -f ~/.ssh/argocd-weather-k8s -N ""
```

**5.2 — Registrar a chave pública no GitHub:**

GitHub → repositório → **Settings → Deploy keys → Add deploy key** → cole o conteúdo de `~/.ssh/argocd-weather-k8s.pub`.  
_(Write access só se o Argo CD precisar escrever no repo — no fluxo comum não é necessário.)_

**5.3 — Criar o Secret no cluster:**

> **Atenção:** abra `scripts/03-apply-argocd-ssh-secret.sh` e confirme que `ARGOCD_REPO_URL_PREFIX` corresponde ao seu usuário GitHub (padrão: `git@github.com:eduaguiar281`). Se o usuário for diferente, passe via variável de ambiente:
> ```bash
> ARGOCD_REPO_URL_PREFIX=git@github.com:SEU_USUARIO ./scripts/03-apply-argocd-ssh-secret.sh
> ```

```bash
./scripts/03-apply-argocd-ssh-secret.sh
```

**5.4 — Conferir que o `repoURL` nos Applications usa SSH:**

Cada arquivo `k8s/argocd/*.yaml` deve ter:

```yaml
spec:
  source:
    repoURL: git@github.com:SEU_USUARIO/weather-k8s.git
```

O Argo CD compara o `repoURL` com o prefixo do Secret: precisam ser **idênticos** (mesma forma, mesmo usuário). Se estiver em HTTPS e quiser SSH, troque apenas a linha `repoURL` nos três arquivos e faça commit + push.

### 6. Aplicar os Applications no cluster

```bash
./scripts/04-apply-argocd-apps.sh           # infra + dev
# ./scripts/04-apply-argocd-apps.sh --prod  # inclui prod também
```

O script aplica os manifests, aguarda o sync inicial e **detecta e corrige automaticamente** o erro de webhook do OpenTelemetry Operator (`connection refused`) que pode ocorrer logo após o bootstrap.

Esperado ao final: `SYNC STATUS = Synced` e `HEALTH STATUS = Healthy` para todos.

### 7. Deploy da weather-api

```bash
./scripts/05-deploy.sh dev    # build + kind load + rollout em dev
./scripts/05-deploy.sh prod   # idem em prod
```

Internamente chama `deploy-dev.sh` e/ou `deploy-prod.sh`.

### 8. Deploy do agente (Alert Agent)

O agente roda no cluster Kubernetes (namespace `weather-agent`) e é gerenciado pelo Argo CD. Ele **não faz parte do Docker Compose**. O código Python está organizado em camadas (`core`, `infra`, `presentation`) e um composition root (`bootstrap`); ver **[agent/README.md — Arquitetura](agent/README.md#arquitetura-camadas)**.

**8.1 — Defina as variáveis de ambiente obrigatórias:**

```bash
export GRAFANA_TOKEN=glsa_SEU_TOKEN_AQUI   # token da service account do Grafana
export LLM_API_KEY=sk-SEU_TOKEN_AQUI       # chave da API do provider LLM
```

Variáveis opcionais (têm padrão):

| Variável | Padrão | Descrição |
|----------|--------|-----------|
| `GRAFANA_URL` | `http://host.docker.internal:3000` | URL do Grafana a partir dos pods (**não use** um IP da `kind_bridge` — Grafana não está anexado a essa rede; veja observação abaixo) |
| `LLM_PROVIDER` | `anthropic` | Provider: `anthropic` ou `openai` |
| `LLM_MODEL` | `claude-sonnet-4-20250514` | Modelo a usar |
| `LLM_BASE_URL` | _(vazio)_ | Proxies/OpenAI-compat: **LM Studio** → `http://host.docker.internal:<porta>/v1` (**não** `/api/v1`) |
| `RABBITMQ_URL` | `amqp://guest:guest@host.docker.internal:5672/` | AMQP usando a porta publicada no host (Compose mapeia `5672`) |
| `RABBITMQ_EXCHANGE` | `weather.agent` | Exchange topic principal |
| `RABBITMQ_ANALYSIS_QUEUE` / `RABBITMQ_ANALYSIS_ROUTING_KEY` | `weather.agent.analysis` / `analysis` | Fila única: análises LLM (`kind: analysis`) e resolved (`kind: resolved`); consumidor com **prefetch baixo** para ordem estrita; o agente declara `x-single-active-consumer` na fila |

> **Redes Docker × Kind:** Na rede externa `observability_observability` (referenciada pelo Compose como `kind_bridge`), ficam apenas **OpenTelemetry Collector** (`172.23.0.50`), **Loki** (`172.23.0.51`) e **RabbitMQ** (`172.23.0.52`). **Grafana não tem IP na `kind_bridge`** — ele está só na rede interna `observability`; por isso o agente deve usar **`http://host.docker.internal:3000`** ou outro nome que alcance o host onde o Grafana expõe a porta **3000**. Em Linux pode ser preciso garantir que `host.docker.internal` existe (Compose já usa `host-gateway` no Alertmanager como referência).

**Webhook e filas:** o `POST /webhook` responde **202 Accepted** com `{"status":"accepted"}` e processa em background: todas as mensagens vão para **`weather.agent.analysis`**. Os campos JSON `kind: "analysis"` (com texto LLM) ou `kind: "resolved"` distinguem firing/pending vs resolvido — **resolved** não passa por LLM nem colecção de métricas/logs no agente. Suba o stack com `docker compose up -d` para ter o RabbitMQ (AMQP `5672`, Management **http://localhost:15672**, usuário/senha `guest`/`guest`). Migrar consumidores da antiga `weather.agent.resolved` para esta fila; se a fila já existir no broker sem `x-single-active-consumer`, pode ser necessário alinhar a topologia (recriar a fila).

Exemplo de consumer local (`aio-pika`):

```python
import asyncio, aio_pika

async def drain(queue_name: str):
    conn = await aio_pika.connect_robust("amqp://guest:guest@localhost:5672/")
    async with conn:
        ch = await conn.channel()
        q = await ch.declare_queue(queue_name, durable=True)
        async with q.iterator() as it:
            async for msg in it:
                async with msg.process():
                    print(msg.body.decode())

asyncio.run(drain("weather.agent.analysis"))
```

**8.2 — Execute o deploy:**

```bash
./scripts/05-deploy.sh agent
# ou diretamente:
./scripts/deploy-agent.sh
```

O script realiza: build da imagem → `kind load` → criação do Secret no cluster → aplicação do Application ArgoCD → aguarda rollout → configura port-forward.

**8.3 — Verifique:**

```bash
kubectl get pods -n weather-agent
curl http://localhost:9093/health
```

**8.3a — Alertas Prometheus → Alertmanager → agente**

As regras em `prometheus/rules/` disparam no **Prometheus** e as notificações saem pelo **Alertmanager** (`alertmanager/alertmanager.yml`), com webhook para `http://host.docker.internal:9093/webhook` (porta **9093** no host: mesmo port-forward do agente no passo 8.2 e o script `scripts/apps/map-ports.sh`). O serviço `alertmanager` no Compose inclui `extra_hosts` para `host.docker.internal` funcionar também no Linux.

A UI do Alertmanager no host está em **http://localhost:9094** (no Compose, `9094:9093`), para a porta **9093** do host ficar reservada ao webhook do agente.

Após alterar o YAML do Alertmanager: `docker compose up -d --force-recreate alertmanager`.

**8.4 — Configure o webhook no Grafana:**

1. Acesse **http://localhost:3000**
2. Vá em **Alerting → Contact points → New contact point**
3. Tipo: **Webhook**
4. URL: `http://alert-agent.weather-agent.svc.cluster.local/webhook` (interno ao cluster)
   ou `http://localhost:9093/webhook` (via port-forward na porta **9093**)
5. Salve e adicione ao seu **Notification policy**

**Para fazer deploy de tudo de uma vez:**

```bash
./scripts/05-deploy.sh all    # dev + prod + agente
```

### 9. Ponte Kind ↔ Docker Compose (telemetria)

Execute sempre que reiniciar o cluster Kind ou o Compose:

```bash
./scripts/06-setup-kind-network.sh
```

### 10. Acessar as UIs (opcional)

**Argo CD:**
```bash
kubectl port-forward svc/argocd-server -n argocd 8080:443
```
Abra **https://localhost:8080** — usuário `admin`, senha:
```bash
kubectl -n argocd get secret argocd-initial-admin-secret \
  -o jsonpath='{.data.password}' | base64 -d && echo
```

---

## Troubleshooting

### `kubectl` aponta para `localhost:8080` (connection refused)

O kubeconfig está errado — o cliente tenta falar com `http://localhost:8080` em vez do endpoint do Kind.

```bash
kind get clusters
kubectl config get-contexts
kubectl config use-context kind-local
kind export kubeconfig --name local
kubectl cluster-info
```

Se o cluster não existir mais, recrie: `./scripts/02-bootstrap-kind-argocd.sh`.

**Onde está o Argo CD:** roda como pods dentro do Kind, não como container Docker solto. Para ver: `kubectl get pods -n argocd` com o contexto `kind-local` ativo.

### O cluster Kind "desapareceu"

Clusters Kind são containers Docker — se o Docker reiniciar ou o container for removido, o cluster some. Recrie com:

```bash
./scripts/02-bootstrap-kind-argocd.sh
```

> `kind delete cluster --name local` **apaga** o cluster intencionalmente. Não faz parte do fluxo normal — só use se quiser descartar tudo.

### Argo CD: `Too long` ao instalar CRDs

O script usa `kubectl apply --server-side --force-conflicts`, que evita o problema. Se já instalou sem `--server-side` e encontrou o erro:

```bash
kubectl delete namespace argocd
./scripts/02-bootstrap-kind-argocd.sh
```

### Argo CD: `ssh: no key found` ou erro de autenticação Git

1. Confirme que o Secret existe: `kubectl get secret repo-weather-k8s-ssh-creds -n argocd`
2. Rode novamente: `./scripts/03-apply-argocd-ssh-secret.sh`
3. Confirme que `repoURL` nos Applications é `git@github.com:SEU_USUARIO/...` (não HTTPS)
4. Confirme que a chave pública está registrada no GitHub (Deploy keys ou SSH keys da conta)

### Applications OutOfSync por erro de webhook do OTel Operator

O script `04-apply-argocd-apps.sh` detecta e corrige isso automaticamente. Se precisar corrigir manualmente:

```bash
kubectl delete application weather-api-dev -n argocd
kubectl apply -f k8s/argocd/weather-api-dev.yaml
```

---

## Integração com Cursor MCP (Model Context Protocol)

Este projeto utiliza servidores MCP para permitir que o Cursor AI interaja diretamente com ferramentas de observabilidade, como o Grafana.

### Configuração obrigatória: arquivo global `~/.cursor/mcp.json`

> **Atenção:** o arquivo `mcp.json` deve ser criado **globalmente** na pasta `~/.cursor/`, e **não** dentro do repositório. Ele contém tokens sensíveis e é específico por máquina.

Crie o arquivo `~/.cursor/mcp.json` com o seguinte conteúdo de exemplo:

```json
{
  "mcpServers": {
    "grafana": {
      "command": "docker",
      "args": [
        "run", "--rm", "-i",
        "--network", "host",
        "-e", "GRAFANA_URL",
        "-e", "GRAFANA_SERVICE_ACCOUNT_TOKEN",
        "grafana/mcp-grafana",
        "-t", "stdio"
      ],
      "env": {
        "GRAFANA_URL": "http://localhost:3000",
        "GRAFANA_SERVICE_ACCOUNT_TOKEN": "glsa_SEU_TOKEN_AQUI"
      }
    }
  }
}
```

#### Como gerar o token do Grafana

1. Acesse o Grafana: **http://localhost:3000**
2. Vá em **Administration → Service Accounts → Add service account**
3. Dê o papel **Viewer** (ou **Editor** se precisar escrever)
4. Clique em **Add service account token** e copie o valor gerado
5. Substitua `glsa_SEU_TOKEN_AQUI` pelo token no `~/.cursor/mcp.json`

#### Por que global e não no repositório?

| Local | Motivo |
|-------|--------|
| `~/.cursor/mcp.json` | Correto — tokens ficam fora do repositório, configuração por máquina |
| `.cursor/mcp.json` (no repo) | Evitar — risco de vazar tokens no histórico Git |

Após criar ou editar o arquivo, **reinicie o Cursor** para que os servidores MCP sejam carregados.

---

## Estrutura do repositório

| Caminho | Descrição |
|---------|-----------|
| `kind/cluster-config.yaml` | Configuração do cluster Kind (um control-plane) |
| `docker-compose.yml` | Stack de observabilidade + Postgres + RabbitMQ (Prometheus, Loki, Grafana, etc.) |
| `rabbitmq/` | Config do broker RabbitMQ (`kind_bridge`: `172.23.0.52`; no host também `localhost:5672`) |
| `scripts/01-ensure-observability-network.sh` | Cria a rede Docker externa antes do `docker compose up` |
| `scripts/02-bootstrap-kind-argocd.sh` | Bootstrap: Kind + cert-manager + OTel Operator + Argo CD |
| `scripts/03-apply-argocd-ssh-secret.sh` | Cria o Secret SSH no Argo CD a partir de `~/.ssh/argocd-weather-k8s` |
| `scripts/04-apply-argocd-apps.sh` | Aplica os Applications do Argo CD (com retry automático do webhook OTel) |
| `scripts/05-deploy.sh` | Orquestrador de deploy: `dev`, `prod`, `agent` ou `all` |
| `scripts/06-setup-kind-network.sh` | Ponte de rede Kind ↔ Docker Compose |
| `scripts/deploy-dev.sh` | Build + `kind load` + rollout da weather-api em dev (chamado pelo 05) |
| `scripts/deploy-prod.sh` | Build + `kind load` + rollout da weather-api em prod (chamado pelo 05) |
| `scripts/deploy-agent.sh` | Build + `kind load` + Secret + rollout do agente (chamado pelo 05) |
| `k8s/base/` | Manifests base da weather-api (Kustomize) |
| `k8s/overlays/` | Overlays dev e prod da weather-api |
| `k8s/agent/` | Manifests do agente: namespace, deployment, service, instrumentation OTel |
| `k8s/agent/secret.yaml.example` | Template do Secret do agente (valores reais criados pelo script) |
| `k8s/argocd/` | Applications do Argo CD (weather-api-dev, weather-api-prod, weather-agent, weather-infra) |
| `k8s/argocd/repo-github-ssh.secret.yaml.example` | Referência manual do Secret SSH (prefira o script) |
| `k8s/infra/` | Manifests de infraestrutura (Promtail, etc.) |
| `app/` | Código da weather-api FastAPI (ver `app/README.md`) |
| `agent/` | Código do agente de alertas com LLM (ver `agent/README.md`) |
