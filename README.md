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

### 7. Deploy da imagem local

```bash
./scripts/05-deploy.sh dev    # build + kind load + rollout em dev
./scripts/05-deploy.sh prod   # idem em prod
./scripts/05-deploy.sh all    # os dois
```

Internamente chama `deploy-dev.sh` e/ou `deploy-prod.sh`.

### 8. Ponte Kind ↔ Docker Compose (telemetria)

Execute sempre que reiniciar o cluster Kind ou o Compose:

```bash
./scripts/06-setup-kind-network.sh
```

### 9. Acessar as UIs (opcional)

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
| `docker-compose.yml` | Stack de observabilidade + API + Postgres |
| `scripts/01-ensure-observability-network.sh` | Cria a rede Docker externa antes do `docker compose up` |
| `scripts/02-bootstrap-kind-argocd.sh` | Bootstrap: Kind + cert-manager + OTel Operator + Argo CD |
| `scripts/03-apply-argocd-ssh-secret.sh` | Cria o Secret SSH no Argo CD a partir de `~/.ssh/argocd-weather-k8s` |
| `scripts/04-apply-argocd-apps.sh` | Aplica os Applications do Argo CD (com retry automático do webhook OTel) |
| `scripts/05-deploy.sh` | Orquestrador de deploy: `dev`, `prod` ou `all` |
| `scripts/06-setup-kind-network.sh` | Ponte de rede Kind ↔ Docker Compose |
| `scripts/deploy-dev.sh` | Build + `kind load` + rollout da imagem de dev (chamado pelo 05) |
| `scripts/deploy-prod.sh` | Build + `kind load` + rollout da imagem de prod (chamado pelo 05) |
| `k8s/argocd/` | Manifests dos Applications do Argo CD |
| `k8s/argocd/repo-github-ssh.secret.yaml.example` | Referência manual do Secret SSH (prefira o script) |
| `k8s/` | Manifests base, overlays e apps Argo CD |
| `app/` | API FastAPI (ver `app/README.md`) |
