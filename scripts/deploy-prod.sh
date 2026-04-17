#!/bin/bash
# Deploy da aplicação no ambiente de produção (namespace: weather)
# Pré-requisitos: kind cluster rodando, docker-compose up -d, setup-kind-network.sh executado

set -e

OVERLAY="k8s/overlays/prod"
NAMESPACE="weather"
IMAGE_NAME="weather-api:local"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"

echo "==> [PROD] Build da imagem Docker..."
docker build -t "$IMAGE_NAME" "$ROOT_DIR/app"

echo "==> [PROD] Carregando imagem no kind..."
kind load docker-image "$IMAGE_NAME" --name local

echo "==> [INFRA] Aplicando infraestrutura compartilhada (Promtail)..."
kubectl apply -k "$ROOT_DIR/k8s/infra"

echo "==> [PROD] Aplicando manifests (namespace: $NAMESPACE)..."
kubectl apply -k "$ROOT_DIR/$OVERLAY"

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
