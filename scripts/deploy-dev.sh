#!/bin/bash
# Deploy da aplicação no ambiente de desenvolvimento (namespace: weather-dev)
# Pré-requisitos: kind cluster rodando, docker-compose up -d, setup-kind-network.sh executado
#
# Fluxo:
#   1. Build da imagem Docker
#   2. Carrega imagem no kind (necessário pois imagePullPolicy: Never)
#   3. ArgoCD detecta o novo deployment e sincroniza automaticamente

set -e

NAMESPACE="weather-dev"
IMAGE_NAME="weather-api:local"
ARGOCD_APP="weather-api-dev"
ARGOCD_INFRA_APP="weather-infra"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"

echo "==> [DEV] Build da imagem Docker..."
docker build -t "$IMAGE_NAME" "$ROOT_DIR/app"

echo "==> [DEV] Carregando imagem no kind..."
kind load docker-image "$IMAGE_NAME" --name local

echo "==> [INFRA] Garantindo Applications do ArgoCD..."
kubectl apply -f "$ROOT_DIR/k8s/argocd/weather-infra.yaml"
kubectl apply -f "$ROOT_DIR/k8s/argocd/weather-api-dev.yaml"

echo "==> [DEV] Aguardando Argo CD sincronizar e criar o deployment em ${NAMESPACE}..."
attempts=0
max_attempts=60
while ! kubectl get deployment weather-api -n "$NAMESPACE" >/dev/null 2>&1; do
  attempts=$((attempts + 1))
  if [[ "$attempts" -ge "$max_attempts" ]]; then
    echo "Erro: deployment weather-api não apareceu após ~$((max_attempts * 3))s." >&2
    echo "Confira o app no Argo CD: kubectl get application weather-api-dev -n argocd -o yaml" >&2
    exit 1
  fi
  sleep 3
done

echo "==> [DEV] Forçando rollout para pegar nova imagem..."
kubectl rollout restart deployment/weather-api -n "$NAMESPACE"

echo "==> [DEV] Aguardando rollout..."
kubectl rollout status deployment/weather-api -n "$NAMESPACE" --timeout=120s

echo ""
echo "==> Restaurando port-forward para dev..."
pkill -f "kubectl port-forward svc/weather-api -n $NAMESPACE" 2>/dev/null || true
sleep 1
kubectl port-forward svc/weather-api -n "$NAMESPACE" 9092:80 &>/dev/null &
echo "    weather-api (dev) → localhost:9092"

echo ""
echo "✓ Deploy DEV concluído!"
echo "  GET http://localhost:9092/live"
echo "  GET http://localhost:9092/hello"
echo "  GET http://localhost:9092/weather?city=Curitiba"
