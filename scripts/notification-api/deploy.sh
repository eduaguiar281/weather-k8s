#!/usr/bin/env bash
# Deploy do shape-notification-api via GitOps (ArgoCD).
#
# Este script cuida apenas do que não pode ir pelo git:
#   1. Carrega a imagem no kind (imagePullPolicy: Never)
#   2. Aplica o secret com as credenciais (gitignored)
#   3. Força rollout para o pod pegar a nova imagem
#   4. Inicia port-forward na porta 5000
#
# O ArgoCD sincroniza os demais manifests automaticamente a partir do repo.
#
# Pré-requisitos:
#   - kind cluster rodando
#   - Imagem shape-notification-api:local disponível localmente
#   - k8s/argocd/notification-api/secret.yaml preenchido com valores reais
#
# Uso:
#   ./scripts/notification-api/deploy.sh

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "$SCRIPT_DIR/../.." && pwd)"

NAMESPACE="notification-api"
IMAGE_NAME="shape-notification-api:local"
MANIFEST_DIR="$ROOT_DIR/k8s/argocd/notification-api"
SECRET_FILE="$MANIFEST_DIR/secret.yaml"

echo "==> [NOTIFICATION-API] Carregando imagem no kind..."
kind load docker-image "$IMAGE_NAME" --name local

echo "==> [NOTIFICATION-API] Garantindo que o namespace existe..."
kubectl apply -f "$MANIFEST_DIR/namespace.yaml"

echo "==> [NOTIFICATION-API] Aplicando secret (fora do ArgoCD)..."
kubectl apply -f "$SECRET_FILE"

echo "==> [NOTIFICATION-API] Aguardando ArgoCD sincronizar..."
kubectl wait application/shape-notification-api -n argocd \
  --for=jsonpath='{.status.sync.status}'=Synced --timeout=60s 2>/dev/null || true

echo "==> [NOTIFICATION-API] Forçando rollout para pegar nova imagem..."
kubectl rollout restart deployment/shape-notification-api -n "$NAMESPACE"
kubectl rollout status deployment/shape-notification-api -n "$NAMESPACE" --timeout=120s

echo ""
echo "==> Restaurando port-forward..."
pkill -f "kubectl port-forward svc/shape-notification-api -n $NAMESPACE" 2>/dev/null || true
sleep 1
kubectl port-forward svc/shape-notification-api -n "$NAMESPACE" 5000:8000 &>/dev/null &

echo ""
echo "✓ Deploy NOTIFICATION-API concluído!"
echo "  http://localhost:5000"
