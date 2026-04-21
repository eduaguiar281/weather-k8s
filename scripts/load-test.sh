#!/bin/bash
# Gera tráfego para a Weather API: requisições corretas, erros 400 e exceções.
#
# Uso:
#   ./load-test.sh --iterations <N> --env <dev|prod> [--sleep <segundos>]
#
# Exemplos:
#   ./load-test.sh --iterations 10 --env dev
#   ./load-test.sh --iterations 5 --env prod --sleep 1
#   ./load-test.sh --iterations 10 --env dev -s 0.2

set -e

# ── Defaults ────────────────────────────────────────────────
ITERATIONS=5
ENV="dev"
SLEEP=0.5

# ── Parse args ──────────────────────────────────────────────
while [[ $# -gt 0 ]]; do
  case "$1" in
    --iterations|-i) ITERATIONS="$2"; shift 2 ;;
    --env|-e)        ENV="$2";        shift 2 ;;
    --sleep|-s)      SLEEP="$2";      shift 2 ;;
    *)
      echo "Uso: $0 --iterations <N> --env <dev|prod> [--sleep <segundos>]"
      exit 1
      ;;
  esac
done

# ── Resolve porta por ambiente ───────────────────────────────
case "$ENV" in
  dev)  PORT=9092 ;;
  prod) PORT=9091 ;;
  *)
    echo "Erro: --env deve ser 'dev' ou 'prod' (recebido: '$ENV')"
    exit 1
    ;;
esac

BASE_URL="http://localhost:${PORT}"

# ── Cores ────────────────────────────────────────────────────
GREEN='\033[0;32m'
RED='\033[0;31m'
YELLOW='\033[1;33m'
NC='\033[0m'

# ── Funções ──────────────────────────────────────────────────
do_request() {
  local label="$1"
  local url="$2"
  local status

  status=$(curl -s -o /dev/null -w "%{http_code}" "$url")

  if [[ "$status" =~ ^2 ]]; then
    echo -e "  ${GREEN}[${status}] OK${NC}      ${label}"
  elif [[ "$status" =~ ^4 ]]; then
    echo -e "  ${YELLOW}[${status}] ERRO${NC}    ${label}"
  else
    echo -e "  ${RED}[${status}] FALHA${NC}   ${label}"
  fi

  sleep "$SLEEP"
}

# ── Requisições corretas ─────────────────────────────────────
CORRECT_REQUESTS=(
  "GET /live|${BASE_URL}/live"
  "GET /hello|${BASE_URL}/hello"
  "GET /weather Curitiba|${BASE_URL}/weather?city=Curitiba"
  "GET /weather São Paulo|${BASE_URL}/weather?city=S%C3%A3o%20Paulo"
  "GET /weather com data|${BASE_URL}/weather?city=Manaus&date=2024-04-01"
)

# ── Requisições com erro 400 ─────────────────────────────────
# Cidade com mais de 50 caracteres → HTTP 400
BAD_CITY="EstaCidadeTemUmNomeMuitoLongoQueUltrapassaOLimiteDe50Chars"
BAD_REQ_400="${BASE_URL}/weather?city=${BAD_CITY}"

# ── Requisição que gera exceção (422 Unprocessable Entity) ────
# Parâmetro obrigatório `city` ausente → FastAPI lança RequestValidationError
EXCEPTION_REQ="${BASE_URL}/weather?date=2024-04-01"

# ── Loop principal ───────────────────────────────────────────
echo ""
echo "========================================"
echo "  Load Test — env: ${ENV}  porta: ${PORT}"
echo "  Iterações: ${ITERATIONS}  sleep: ${SLEEP}s"
echo "========================================"

for ((iter=1; iter<=ITERATIONS; iter++)); do
  echo ""
  echo "── Iteração ${iter}/${ITERATIONS} ─────────────────────"

  # 5 requisições corretas (rota entre as opções disponíveis)
  for entry in "${CORRECT_REQUESTS[@]}"; do
    label="${entry%%|*}"
    url="${entry##*|}"
    do_request "$label" "$url"
  done

  # 1 requisição com erro 400
  do_request "GET /weather cidade longa (→ 400)" "$BAD_REQ_400"

  # 1 requisição que gera exceção (422)
  do_request "GET /weather sem city (→ 422)" "$EXCEPTION_REQ"

done

echo ""
echo "========================================"
echo "  Concluído: $((ITERATIONS * 7)) requisições enviadas"
echo "  (${ITERATIONS}×5 corretas + ${ITERATIONS}×1 erro 400 + ${ITERATIONS}×1 exceção)"
echo "========================================"
echo ""
