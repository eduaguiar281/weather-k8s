#!/bin/bash
# Deploy da aplicação no ambiente de produção (namespace: weather)
# Pré-requisitos: kind cluster rodando, docker-compose up -d, setup-kind-network.sh executado
#
# Fluxo:
#   1. Build da imagem Docker
#   2. Carrega imagem no kind (necessário pois imagePullPolicy: Never)
#   3. ArgoCD detecta o novo deployment e sincroniza automaticamente

set -e

NAMESPACE="weather"
IMAGE_NAME="weather-api:local"
ARGOCD_APP="weather-api"
ARGOCD_INFRA_APP="weather-infra"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"

echo "==> [PROD] Build da imagem Docker..."
docker build -t "$IMAGE_NAME" "$ROOT_DIR/app"

echo "==> [PROD] Carregando imagem no kind..."
kind load docker-image "$IMAGE_NAME" --name local

echo "==> [INFRA] Garantindo Applications do ArgoCD..."
kubectl apply -f "$ROOT_DIR/k8s/argocd/weather-infra.yaml"
kubectl apply -f "$ROOT_DIR/k8s/argocd/weather-api-prod.yaml"

echo "==> [PROD] Forçando rollout para pegar nova imagem..."
kubectl rollout restart deployment/weather-api -n "$NAMESPACE"

echo "==> [PROD] Aguardando rollout..."
kubectl rollout status deployment/weather-api -n "$NAMESPACE" --timeout=120s

echo ""
echo "==> Restaurando port-forward para prod..."
pkill -f "kubectl port-forward svc/weather-api -n $NAMESPACE" 2>/dev/null || true
sleep 1
kubectl port-forward svc/weather-api -n "$NAMESPACE" 9091:80 &>/dev/null &
echo "    weather-api (prod) → localhost:9091"

echo ""
echo "✓ Deploy PROD concluído!"
echo "  GET http://localhost:9091/live"
echo "  GET http://localhost:9091/hello"
echo "  GET http://localhost:9091/weather?city=Curitiba"
