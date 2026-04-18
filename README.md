# weather-k8s

Stack de exemplo com API de clima, manifests Kubernetes (Kustomize), observabilidade via Docker Compose e GitOps com **Kind** (Kubernetes in Docker) e **Argo CD**.

Este documento cobre o ambiente local desde o zero: cluster Kind, instalação do Argo CD e notas para **macOS** e **Linux (incluindo WSL2)** sem depender de caminhos ou ferramentas específicos de uma única plataforma.

## Pré-requisitos

| Ferramenta | Função |
|------------|--------|
| [Docker](https://docs.docker.com/get-docker/) | Motor de containers usado pelo Kind |
| [Kind](https://kind.sigs.k8s.io/docs/user/quick-start/#installation) | Cria o cluster Kubernetes local |
| [kubectl](https://kubernetes.io/docs/tasks/tools/) | CLI do Kubernetes |

**Regra geral:** use os binários no `PATH` e o mesmo contexto `kubectl` que o Kind configurar (`kind-local` quando o cluster se chama `local`). Os scripts do repositório assumem o cluster **`local`** para alinhar com `kind load docker-image --name local` e com o nó Docker `local-control-plane`.

### macOS

Instalação típica com Homebrew:

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

## Passo a passo completo (ordem)

Siga nesta ordem. Em cada etapa, só avance se o “como verificar” estiver ok.

### 1. Ferramentas e Docker

- Instale **Docker** (Desktop no Mac), **kind** e **kubectl** e confira:

  ```bash
  docker info
  kind version
  kubectl version --client
  ```

### 2. Repositório Git no GitHub (importante para o Argo CD)

O Argo CD **clona o Git remoto** (`repoURL` em `k8s/argocd/*.yaml`), não o seu diretório local. **Commits que não estiverem no GitHub não entram no sync.**

- Faça **commit e push** do branch que você usa (ex.: `main`) para `origin` antes de confiar no sync.
- O `repoURL` deve ser **HTTPS** para repo público (`https://github.com/.../weather-k8s.git`). Repo **privado** exige [credencial no Argo CD](https://argo-cd.readthedocs.io/en/stable/user-guide/private-repositories/).

### 3. Rede Docker do Compose + stack de observabilidade

Na **raiz** do repositório:

```bash
./scripts/ensure-observability-network.sh
docker compose up -d
```

Verificar: `docker compose ps` (serviços `Up`).

### 4. Cluster Kind + Argo CD

```bash
./scripts/bootstrap-kind-argocd.sh
kubectl config use-context kind-local
kubectl get pods -n argocd
```

Verificar: pods do `argocd` em `Running` (pode levar alguns minutos na primeira vez). Se `argocd-server` ficar `Pending`, use `kubectl describe pod -n argocd -l app.kubernetes.io/name=argocd-server` e aguarde pull de imagem ou recursos.

### 5. Registrar os Applications no cluster

```bash
kubectl apply -f k8s/argocd/weather-infra.yaml
kubectl apply -f k8s/argocd/weather-api-dev.yaml
# opcional — prod:
# kubectl apply -f k8s/argocd/weather-api-prod.yaml
```

Verificar até **Sync Status = Synced** (e sem `ComparisonError`):

```bash
kubectl get application -n argocd
```

Se aparecer erro de Git/SSH, confira se o `repoURL` nos YAML está em **HTTPS** e se o push para o GitHub foi feito.

### 6. Deploy da imagem local (dev)

Com o passo 5 ok:

```bash
./scripts/deploy-dev.sh
```

### 7. Ponte Kind ↔ Docker Compose (telemetria / rede)

Com Kind e Compose no ar:

```bash
./scripts/setup-kind-network.sh
```

### 8. UIs (opcional)

- **Argo CD:** `kubectl port-forward svc/argocd-server -n argocd 8080:443` → https://localhost:8080  
- Senha admin: `kubectl -n argocd get secret argocd-initial-admin-secret -o jsonpath='{.data.password}' | base64 -d && echo`

---

## Subir o cluster Kind e instalar o Argo CD

A partir da raiz do repositório:

```bash
chmod +x scripts/bootstrap-kind-argocd.sh   # uma vez
./scripts/bootstrap-kind-argocd.sh
```

O script:

1. Verifica Docker, `kind` e `kubectl`.
2. Cria o cluster **`local`** com `kind/cluster-config.yaml` (se ainda não existir).
3. Instala o Argo CD no namespace `argocd` (se ainda não estiver instalado).
4. Mostra como obter a senha inicial do usuário `admin` e como expor a UI.

### Versão do Argo CD

Por padrão o manifest **`stable`** do projeto Argo CD é aplicado. Para fixar uma versão (builds reproduzíveis):

```bash
ARGOCD_VERSION=v2.13.4 ./scripts/bootstrap-kind-argocd.sh
```

Substitua pela tag desejada no repositório [argoproj/argo-cd](https://github.com/argoproj/argo-cd/releases).

Se uma execução antiga falhou com *metadata.annotations: Too long* no CRD `applicationsets`, rode de novo `./scripts/bootstrap-kind-argocd.sh` (o script usa `kubectl apply --server-side` e só pula a instalação quando o deployment e o CRD `applicationsets.argoproj.io` já existem). Em último caso: `kubectl delete namespace argocd` e execute o bootstrap outra vez.

### Acessar a interface web do Argo CD

Em outro terminal:

```bash
kubectl port-forward svc/argocd-server -n argocd 8080:443
```

Abra **https://localhost:8080** — usuário **admin**, senha impressa pelo script (ou obtida com o comando abaixo). O certificado é autofirmado; aceite o aviso do navegador.

#### Se aparecer `connection refused` em `localhost:8080` ao rodar *qualquer* `kubectl`

Isso costuma ser o **cliente `kubectl` falhando ao falar com a API do Kubernetes**, não o Argo CD “sumindo”. O log que cita `Get "http://localhost:8080/api..."` indica que o **kubeconfig** está com `server` apontando para `http://localhost:8080` (nada escutando aí) em vez do endpoint do Kind (normalmente `https://127.0.0.1:<porta>`).

Confira e corrija:

```bash
kind get clusters
kubectl config get-contexts
kubectl config use-context kind-local
kind export kubeconfig --name local
kubectl cluster-info
```

Se o cluster não existir mais, recrie com `./scripts/bootstrap-kind-argocd.sh` (ou `kind create cluster --name local --config kind/cluster-config.yaml`).

**Onde “está” o Argo CD:** ele roda **como pods dentro do cluster Kind**, não como um container Docker solto com o nome `argocd`. No Docker você costuma ver o nó do Kind (por exemplo `local-control-plane`). Para ver o Argo: `kubectl get pods -n argocd` com o contexto `kind-local` ativo.

```bash
kubectl -n argocd get secret argocd-initial-admin-secret \
  -o jsonpath='{.data.password}' | base64 -d && echo
```

### Apagar o cluster local (opcional — **não** é passo do fluxo normal)

**Não faz parte da instalação nem do dia a dia.** Só serve quando você **quer mesmo descartar** o cluster de desenvolvimento e tudo que roda nele (incluindo Argo CD e aplicações). Se o objetivo é só “ter de novo” um cluster que sumiu, use `./scripts/bootstrap-kind-argocd.sh` — não apague antes.

Se, e somente se, for intencional apagar: `kind delete cluster --name local`.

## Observabilidade (Docker Compose) e ponte com o Kind

O `docker-compose.yml` sobe Grafana, Prometheus, Loki, Jaeger, OpenTelemetry Collector, PostgreSQL, a API, etc. Parte dos serviços usa a rede Docker externa **`observability_observability`** (alias `kind_bridge` no Compose) para IPs fixos (`172.23.0.50` / `172.23.0.51`) e para o nó do Kind se conectar à mesma ponte que o stack de observabilidade.

**Ordem recomendada no primeiro uso:**

1. **Garantir a rede Docker** (uma vez, antes do `compose up`). O script cria a rede externa **`observability_observability`** com subnet **`172.23.0.0/16`** e gateway **`172.23.0.1`**, alinhada aos IPs fixos do Compose (Loki / OTel) e ao `COMPOSE_CIDR` em `scripts/setup-kind-network.sh`. Se a rede já existir, o script não altera nada.

   ```bash
   chmod +x scripts/ensure-observability-network.sh   # uma vez
   ./scripts/ensure-observability-network.sh
   ```

2. **Subir o Compose** na raiz do repositório:

   ```bash
   docker compose up -d
   ```

   (Em ambientes mais antigos o comando pode ser `docker-compose up -d`.)

3. **Cluster Kind + Argo CD** — conforme a seção [Subir o cluster Kind e instalar o Argo CD](#subir-o-cluster-kind-e-instalar-o-argo-cd) (`./scripts/bootstrap-kind-argocd.sh`).

4. **Conectar o Kind à rede do Compose** (roteamento pods ↔ stack Docker). Execute sempre que reiniciar o cluster Kind ou o Compose:

   ```bash
   chmod +x scripts/setup-kind-network.sh   # uma vez
   ./scripts/setup-kind-network.sh
   ```

   O script conecta o container do nó **`local-control-plane`** à rede `observability_observability`, ajusta `iptables` no nó e inicia `kubectl port-forward` para a API e para o Argo CD (portas locais indicadas ao final do script).

**Mac e WSL:** o fluxo é o mesmo; use sempre o Docker do mesmo ambiente em que o Kind e o Compose rodam. No WSL2, não misture `kubectl`/Compose do Windows com o cluster criado dentro da distro.

Se `docker compose up` falhar com *network … declared as external, but could not be found*, a rede `observability_observability` ainda não existe — rode `./scripts/ensure-observability-network.sh` e suba o Compose de novo.

## Argo CD: GitHub via SSH (passo a passo)

Seu `~/.ssh` no Mac/WSL **não** é usado pelos pods do Argo CD. É preciso uma **chave só para o cluster** (Secret) e o `repoURL` dos Applications em **`git@github.com:...`**.

1. **Gerar um par de chaves dedicado** (recomendado; não reuse a chave pessoal). **Sem passphrase** no arquivo que o Argo vai ler (senão costuma complicar):
   ```bash
   ssh-keygen -t ed25519 -f ~/.ssh/argocd-weather-k8s -N ""
   ```
2. **Registrar a chave pública no GitHub** (o repo `weather-k8s`):
   - GitHub → repositório → **Settings** → **Deploy keys** → **Add deploy key** → cole o conteúdo de `~/.ssh/argocd-weather-k8s.pub` → marque **Allow write access** só se precisar que o Argo escreva no repo (no fluxo comum, **não** é necessário).
   - Alternativa: adicionar a mesma pubkey em **SSH keys** da sua conta GitHub (vale para todos os repos da conta).
3. **Criar o Secret no namespace `argocd`** a partir do exemplo (troque `eduaguiar281` no URL se for outro usuário/org):
   ```bash
   cp k8s/argocd/repo-github-ssh.secret.yaml.example k8s/argocd/repo-github-ssh.secret.yaml
   # Edite repo-github-ssh.secret.yaml e cole a chave PRIVADA completa (incluindo BEGIN/END)
   kubectl apply -f k8s/argocd/repo-github-ssh.secret.yaml
   ```
   O ficheiro `repo-github-ssh.secret.yaml` está no `.gitignore` para não subir chave por engano.
4. **`spec.source.repoURL` nos Applications (alinhado ao Secret)**  
   Cada recurso `Application` do Argo CD diz **de onde** buscar o Git: é o campo `spec.source.repoURL`. O Argo compara esse texto com o `url` do Secret: têm de ser **a mesma forma de endereço** (SSH) que você pôs no Secret (`git@github.com:usuario/repo.git`).  
   - Se `repoURL` for `https://github.com/...`, o Argo trata como **outro repositório** e **não** aplica automaticamente a credencial SSH que registou para `git@github.com:...`.  
   - Por isso, nos **três** ficheiros abaixo, troque só a linha `repoURL` de HTTPS para o URL SSH **idêntico** ao do Secret (incluindo `usuário/repo` e `.git` no fim):

   | Ficheiro | Caminho Kustomize / chart |
   |----------|---------------------------|
   | `k8s/argocd/weather-infra.yaml` | `k8s/infra` |
   | `k8s/argocd/weather-api-dev.yaml` | `k8s/overlays/dev` |
   | `k8s/argocd/weather-api-prod.yaml` | `k8s/overlays/prod` |

   **Antes** (exemplo — modo HTTPS):
   ```yaml
   spec:
     source:
       repoURL: https://github.com/eduaguiar281/weather-k8s.git
       path: k8s/overlays/dev
   ```

   **Depois** (modo SSH — o mesmo URL que no Secret):
   ```yaml
   spec:
     source:
       repoURL: git@github.com:eduaguiar281/weather-k8s.git
       path: k8s/overlays/dev
   ```

   Não mude `path` nem `targetRevision` — só **`repoURL`**. Guarde os ficheiros, faça `git add` / `commit` / `push` se quiser que o histórico no GitHub fique coerente; no cluster, o que importa na hora é `kubectl apply -f k8s/argocd/...` com este YAML atualizado.
5. **Aplicar de novo os Applications** e ver o sync:
   ```bash
   kubectl apply -f k8s/argocd/weather-infra.yaml
   kubectl apply -f k8s/argocd/weather-api-dev.yaml
   kubectl get application -n argocd
   ```
6. Se nada mudar, reinicie o repo-server: `kubectl rollout restart deployment/argocd-repo-server -n argocd`.

Referência: [Repositórios privados no Argo CD](https://argo-cd.readthedocs.io/en/stable/user-guide/private-repositories/).

---

## GitOps, deploy da imagem e documentação adicional

- **Modo simples (repo público):** em `k8s/argocd/` use **`repoURL` HTTPS** — não precisa Secret.
- **Modo SSH:** siga a secção [Argo CD: GitHub via SSH](#argo-cd-github-via-ssh-passo-a-passo) acima. Repo **privado** por HTTPS exige PAT/credencial na [documentação oficial](https://argo-cd.readthedocs.io/en/stable/user-guide/private-repositories/).
- **Deploy local da imagem** (build + `kind load` + rollout): `scripts/deploy-dev.sh` e `scripts/deploy-prod.sh`.

## Estrutura útil

| Caminho | Descrição |
|---------|-----------|
| `kind/cluster-config.yaml` | Configuração do cluster Kind (um control-plane) |
| `docker-compose.yml` | Stack de observabilidade + API + Postgres (rede externa `observability_observability`) |
| `scripts/ensure-observability-network.sh` | Cria a rede Docker externa antes do `docker compose up` |
| `scripts/bootstrap-kind-argocd.sh` | Bootstrap Kind + Argo CD |
| `scripts/setup-kind-network.sh` | Ponte de rede Kind ↔ Docker Compose + port-forwards |
| `k8s/argocd/repo-github-ssh.secret.yaml.example` | Modelo de Secret (SSH) para o GitHub — copie e preencha localmente |
| `k8s/` | Manifests base, overlays e apps Argo CD |
| `app/` | API FastAPI (ver `app/README.md`) |
