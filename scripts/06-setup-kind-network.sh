#!/bin/bash
# Configura a conectividade entre os pods do kind e a rede do Docker Compose.
# Execute este script sempre que o cluster kind ou o Docker Compose for reiniciado.

set -e

KIND_NODE="local-control-plane"
COMPOSE_NETWORK="observability_observability"
COMPOSE_CIDR="172.23.0.0/16"
POD_CIDR="10.244.0.0/16"

echo "==> Verificando se o nó do kind está na rede do Docker Compose..."
if ! docker inspect "$KIND_NODE" --format '{{range .NetworkSettings.Networks}}{{.NetworkID}}{{"\n"}}{{end}}' | grep -q "$(docker network inspect "$COMPOSE_NETWORK" --format '{{.Id}}')"; then
  echo "    Conectando $KIND_NODE à rede $COMPOSE_NETWORK..."
  docker network connect "$COMPOSE_NETWORK" "$KIND_NODE"
else
  echo "    Já conectado."
fi

echo "==> Aplicando regras de iptables FORWARD no nó do kind..."
docker exec "$KIND_NODE" iptables -C FORWARD -d "$COMPOSE_CIDR" -j ACCEPT 2>/dev/null || \
  docker exec "$KIND_NODE" iptables -I FORWARD -d "$COMPOSE_CIDR" -j ACCEPT

docker exec "$KIND_NODE" iptables -C FORWARD -s "$COMPOSE_CIDR" -j ACCEPT 2>/dev/null || \
  docker exec "$KIND_NODE" iptables -I FORWARD -s "$COMPOSE_CIDR" -j ACCEPT

docker exec "$KIND_NODE" iptables -C FORWARD -s "$POD_CIDR" -d "$COMPOSE_CIDR" -j ACCEPT 2>/dev/null || \
  docker exec "$KIND_NODE" iptables -I FORWARD -s "$POD_CIDR" -d "$COMPOSE_CIDR" -j ACCEPT

docker exec "$KIND_NODE" iptables -C FORWARD -s "$COMPOSE_CIDR" -d "$POD_CIDR" -j ACCEPT 2>/dev/null || \
  docker exec "$KIND_NODE" iptables -I FORWARD -s "$COMPOSE_CIDR" -d "$POD_CIDR" -j ACCEPT

echo "==> Aplicando regra de MASQUERADE (NAT para pods alcançarem o Docker Compose)..."
docker exec "$KIND_NODE" iptables -t nat -C POSTROUTING -s "$POD_CIDR" -d "$COMPOSE_CIDR" -j MASQUERADE 2>/dev/null || \
  docker exec "$KIND_NODE" iptables -t nat -A POSTROUTING -s "$POD_CIDR" -d "$COMPOSE_CIDR" -j MASQUERADE

echo ""
echo "==> Restaurando port-forwards..."
pkill -f "kubectl port-forward svc/weather-api" 2>/dev/null || true
pkill -f "kubectl port-forward svc/argocd-server" 2>/dev/null || true
sleep 1
kubectl port-forward svc/weather-api -n weather 9091:80 &>/dev/null &
kubectl port-forward svc/argocd-server -n argocd 8080:443 &>/dev/null &
echo "    weather-api  → localhost:9091"
echo "    argocd       → localhost:8080"

echo ""
echo "✓ Configuração concluída!"
echo ""
echo "  IP do otel-collector na rede kind_bridge: 172.23.0.50"
echo "  Os pods do kind já conseguem enviar telemetria para o OTel Collector."
