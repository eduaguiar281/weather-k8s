#!/usr/bin/env bash
# Garante que a rede Docker externa usada pelo docker-compose.yml exista.
#
# O Compose declara a rede "kind_bridge" como external com nome
# observability_observability. Loki e o OpenTelemetry Collector usam IPs fixos
# nessa rede (172.23.0.50 / 172.23.0.51). O script setup-kind-network.sh
# assume o mesmo bloco CIDR (172.23.0.0/16) para regras de iptables no nó Kind.
#
# Uso (na raiz do repositório):
#   ./scripts/ensure-observability-network.sh
#
# Seguro rodar várias vezes: se a rede já existir, não altera nada.

set -euo pipefail

NETWORK_NAME="observability_observability"
SUBNET="172.23.0.0/16"
GATEWAY="172.23.0.1"

if ! command -v docker >/dev/null 2>&1; then
  echo "Erro: 'docker' não encontrado no PATH." >&2
  exit 1
fi

docker info >/dev/null 2>&1 || {
  echo "Erro: daemon do Docker não está acessível. Inicie o Docker e tente de novo." >&2
  exit 1
}

if docker network inspect "$NETWORK_NAME" >/dev/null 2>&1; then
  echo "Rede Docker '${NETWORK_NAME}' já existe; nada a fazer."
  exit 0
fi

echo "Criando rede Docker '${NETWORK_NAME}' (subnet=${SUBNET}, gateway=${GATEWAY})..."
echo "  Motivo: o docker-compose referencia essa rede como externa; sem ela, 'docker compose up' falha."
docker network create --subnet="$SUBNET" --gateway="$GATEWAY" "$NETWORK_NAME"
echo "Rede criada. Você pode rodar 'docker compose up -d'."
