#!/usr/bin/env bash
# Deploy do pm-file-manager via GitOps (ArgoCD).
#
# Este script cuida apenas do que não pode ir pelo git:
#   1. Carrega a imagem no kind (imagePullPolicy: Never)
#   2. Aplica o secret com as credenciais (gitignored)
#   3. Força rollout para o pod pegar a nova imagem
#
# O ArgoCD sincroniza os demais manifests automaticamente a partir do repo.
#
# Pré-requisitos:
#   - kind cluster rodando
#   - Imagem pm-file-manager:local disponível localmente
#   - k8s/argocd/filemanager/secret.yaml preenchido com valores reais
#
# Uso:
#   ./scripts/filemanager/deploy.sh

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "$SCRIPT_DIR/../.." && pwd)"

NAMESPACE="file-manager"
IMAGE_NAME="pm-file-manager:local"
SECRET_FILE="$ROOT_DIR/k8s/argocd/filemanager/secret.yaml"

echo "==> [FILEMANAGER] Carregando imagem no kind..."
kind load docker-image "$IMAGE_NAME" --name local

echo "==> [FILEMANAGER] Aplicando secret (fora do ArgoCD)..."
kubectl apply -f "$SECRET_FILE"

echo "==> [FILEMANAGER] Aguardando ArgoCD sincronizar..."
kubectl wait application/pm-file-manager -n argocd \
  --for=jsonpath='{.status.sync.status}'=Synced --timeout=60s 2>/dev/null || true

echo "==> [FILEMANAGER] Forçando rollout para pegar nova imagem..."
kubectl rollout restart deployment/pm-file-manager -n "$NAMESPACE"
kubectl rollout status deployment/pm-file-manager -n "$NAMESPACE" --timeout=120s

echo ""
echo "==> Restaurando port-forward..."
pkill -f "kubectl port-forward svc/pm-file-manager -n $NAMESPACE" 2>/dev/null || true
sleep 1
kubectl port-forward svc/pm-file-manager -n "$NAMESPACE" 8001:8001 &>/dev/null &

echo ""
echo "✓ Deploy FILEMANAGER concluído!"
echo "  http://localhost:8001/file-manager"
