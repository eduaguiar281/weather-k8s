#!/usr/bin/env bash
# Deploy do agente no cluster Kind (namespace: weather-agent)
# Pré-requisitos: kind cluster rodando, docker-compose up -d, setup-kind-network.sh executado
#
# Variáveis de ambiente obrigatórias:
#   GRAFANA_TOKEN  — token da service account do Grafana (glsa_...)
#   LLM_API_KEY    — chave de API do provider LLM (Anthropic ou OpenAI)
#
# Variáveis opcionais (têm padrão):
#   GRAFANA_URL    — URL do Grafana acessível pelo cluster (padrão: http://host.docker.internal:3000)
#   LLM_PROVIDER   — anthropic | openai (padrão: anthropic)
#   LLM_MODEL      — modelo a usar (padrão: claude-sonnet-4-20250514)
#   LLM_BASE_URL   — URL base customizada (LM Studio em http://host.docker.internal:<porta>/v1 ; padrão: vazio)
#   RABBITMQ_*     — broker e nomes de fila (padrão AMQP usa host.docker.internal:5672)
#
# Fluxo:
#   1. Build da imagem Docker
#   2. Carrega imagem no kind (necessário pois imagePullPolicy: Never)
#   3. Cria/atualiza o Secret com credenciais (não versionado)
#   4. Aplica o Application ArgoCD
#   5. Aguarda sync do ArgoCD e rollout do deployment
#   6. Port-forward na porta 9093 (webhook/health no host; Alertmanager UI no host está em 9094 — docker-compose)

set -euo pipefail

NAMESPACE="weather-agent"
IMAGE_NAME="alert-agent:local"
ARGOCD_APP="weather-agent"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"

# ── Validação de variáveis obrigatórias ─────────────────────────────────────

if [[ -z "${GRAFANA_TOKEN:-}" ]]; then
  echo "Erro: variável GRAFANA_TOKEN não definida." >&2
  echo "  Export: export GRAFANA_TOKEN=glsa_..." >&2
  exit 1
fi

if [[ -z "${LLM_API_KEY:-}" ]]; then
  echo "Erro: variável LLM_API_KEY não definida." >&2
  echo "  Export: export LLM_API_KEY=sk-..." >&2
  exit 1
fi

# ── Valores com padrão ───────────────────────────────────────────────────────

GRAFANA_URL="${GRAFANA_URL:-http://host.docker.internal:3000}"
LLM_PROVIDER="${LLM_PROVIDER:-anthropic}"
LLM_MODEL="${LLM_MODEL:-claude-sonnet-4-20250514}"
LLM_BASE_URL="${LLM_BASE_URL:-}"

RABBITMQ_URL="${RABBITMQ_URL:-amqp://guest:guest@host.docker.internal:5672/}"
RABBITMQ_EXCHANGE="${RABBITMQ_EXCHANGE:-weather.agent}"
RABBITMQ_ANALYSIS_QUEUE="${RABBITMQ_ANALYSIS_QUEUE:-weather.agent.analysis}"
RABBITMQ_ANALYSIS_ROUTING_KEY="${RABBITMQ_ANALYSIS_ROUTING_KEY:-analysis}"
RABBITMQ_RESOLVED_QUEUE="${RABBITMQ_RESOLVED_QUEUE:-weather.agent.resolved}"
RABBITMQ_RESOLVED_ROUTING_KEY="${RABBITMQ_RESOLVED_ROUTING_KEY:-resolved}"

# ── Build ─────────────────────────────────────────────────────────────────────

echo "==> [AGENT] Build da imagem Docker..."
docker build -t "$IMAGE_NAME" "$ROOT_DIR/agent"

echo "==> [AGENT] Carregando imagem no kind..."
kind load docker-image "$IMAGE_NAME" --name local

# ── Secret ───────────────────────────────────────────────────────────────────

echo "==> [AGENT] Criando/atualizando Secret '${NAMESPACE}/agent-secret'..."
kubectl create namespace "$NAMESPACE" --dry-run=client -o yaml | kubectl apply -f -

kubectl create secret generic agent-secret \
  --namespace="$NAMESPACE" \
  --from-literal=GRAFANA_URL="$GRAFANA_URL" \
  --from-literal=GRAFANA_TOKEN="$GRAFANA_TOKEN" \
  --from-literal=LLM_PROVIDER="$LLM_PROVIDER" \
  --from-literal=LLM_MODEL="$LLM_MODEL" \
  --from-literal=LLM_API_KEY="$LLM_API_KEY" \
  --from-literal=LLM_BASE_URL="$LLM_BASE_URL" \
  --from-literal=RABBITMQ_URL="$RABBITMQ_URL" \
  --from-literal=RABBITMQ_EXCHANGE="$RABBITMQ_EXCHANGE" \
  --from-literal=RABBITMQ_ANALYSIS_QUEUE="$RABBITMQ_ANALYSIS_QUEUE" \
  --from-literal=RABBITMQ_ANALYSIS_ROUTING_KEY="$RABBITMQ_ANALYSIS_ROUTING_KEY" \
  --from-literal=RABBITMQ_RESOLVED_QUEUE="$RABBITMQ_RESOLVED_QUEUE" \
  --from-literal=RABBITMQ_RESOLVED_ROUTING_KEY="$RABBITMQ_RESOLVED_ROUTING_KEY" \
  --dry-run=client -o yaml | kubectl apply -f -

# ── ArgoCD Application ────────────────────────────────────────────────────────

echo "==> [AGENT] Garantindo Application do ArgoCD..."
kubectl apply -f "$ROOT_DIR/k8s/argocd/weather-agent.yaml"

# ── Aguardar deployment ───────────────────────────────────────────────────────

echo "==> [AGENT] Aguardando ArgoCD sincronizar e criar o deployment em ${NAMESPACE}..."
attempts=0
max_attempts=60
while ! kubectl get deployment alert-agent -n "$NAMESPACE" >/dev/null 2>&1; do
  attempts=$((attempts + 1))
  if [[ "$attempts" -ge "$max_attempts" ]]; then
    echo "Erro: deployment alert-agent não apareceu após ~$((max_attempts * 3))s." >&2
    echo "Confira o app no Argo CD: kubectl get application weather-agent -n argocd -o yaml" >&2
    exit 1
  fi
  sleep 3
done

echo "==> [AGENT] Forçando rollout para pegar nova imagem..."
kubectl rollout restart deployment/alert-agent -n "$NAMESPACE"

echo "==> [AGENT] Aguardando rollout..."
kubectl rollout status deployment/alert-agent -n "$NAMESPACE" --timeout=120s

# ── Port-forward ──────────────────────────────────────────────────────────────

echo ""
echo "==> Restaurando port-forward para o agente..."
pkill -f "kubectl port-forward svc/alert-agent -n $NAMESPACE" 2>/dev/null || true
sleep 1
kubectl port-forward svc/alert-agent -n "$NAMESPACE" 9093:80 &>/dev/null &

echo ""
echo "✓ Deploy do agente concluído!"
echo "  GET  http://localhost:9093/health"
echo "  POST http://localhost:9093/webhook"
