#!/usr/bin/env bash
# Orquestrador de deploy: chama deploy-dev.sh e/ou deploy-prod.sh.
#
# Uso:
#   ./scripts/05-deploy.sh dev       # deploy apenas no ambiente de dev
#   ./scripts/05-deploy.sh prod      # deploy apenas no ambiente de prod
#   ./scripts/05-deploy.sh all       # deploy em dev e prod

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

usage() {
  echo "Uso: $0 <dev|prod|all>" >&2
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
  all)
    "$SCRIPT_DIR/deploy-dev.sh"
    "$SCRIPT_DIR/deploy-prod.sh"
    ;;
  *)
    usage
    ;;
esac
