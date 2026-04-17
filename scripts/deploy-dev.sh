#!/bin/bash
# Deploy da aplicação no ambiente de desenvolvimento (namespace: weather-dev)
# Pré-requisitos: kind cluster rodando, docker-compose up -d, setup-kind-network.sh executado

set -e

OVERLAY="k8s/overlays/dev"
NAMESPACE="weather-dev"
IMAGE_NAME="weather-api:local"
KIND_NODE="local-control-plane"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"

echo "==> [DEV] Build da imagem Docker..."
docker build -t "$IMAGE_NAME" "$ROOT_DIR/app"

echo "==> [DEV] Carregando imagem no kind..."
kind load docker-image "$IMAGE_NAME" --name local

echo "==> [INFRA] Aplicando infraestrutura compartilhada (Promtail)..."
kubectl apply -k "$ROOT_DIR/k8s/infra"

echo "==> [DEV] Aplicando manifests (namespace: $NAMESPACE)..."
kubectl apply -k "$ROOT_DIR/$OVERLAY"

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
