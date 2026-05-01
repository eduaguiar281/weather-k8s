#!/usr/bin/env bash
# Orquestrador de deploy: chama deploy-dev.sh, deploy-prod.sh e/ou deploy-agent.sh.
#
# Uso:
#   ./scripts/05-deploy.sh dev       # deploy da weather-api no ambiente de dev
#   ./scripts/05-deploy.sh prod      # deploy da weather-api no ambiente de prod
#   ./scripts/05-deploy.sh agent     # deploy do agente (namespace: weather-agent)
#   ./scripts/05-deploy.sh all       # deploy em dev, prod e agente

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

usage() {
  echo "Uso: $0 <dev|prod|agent|all>" >&2
  exit 1
}

[[ $# -lt 1 ]] && usage

case "$1" in
  dev)
    "$SCRIPT_DIR/deploy-dev.sh"
    ;;
  prod)
    "$SCRIPT_DIR/deploy-prod.sh"
    ;;
  agent)
    "$SCRIPT_DIR/deploy-agent.sh"
    ;;
  all)
    "$SCRIPT_DIR/deploy-dev.sh"
    "$SCRIPT_DIR/deploy-prod.sh"
    "$SCRIPT_DIR/deploy-agent.sh"
    ;;
  *)
    usage
    ;;
esac
