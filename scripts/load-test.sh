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

# ── Cidades disponíveis (nome exibição | URL-encoded) ────────
CITIES_NAME=("Fortaleza" "Manaus" "Curitiba" "Rio de Janeiro" "São Paulo")
CITIES_URL=("Fortaleza" "Manaus" "Curitiba" "Rio%20de%20Janeiro" "S%C3%A3o%20Paulo")

# ── Contadores por cidade (índice paralelo a CITIES_NAME) ────
CITY_COUNT=(0 0 0 0 0)

# ── Datas disponíveis (01/04/2024 a 10/04/2024) ─────────────
DATES=(
  "2024-04-01" "2024-04-02" "2024-04-03" "2024-04-04" "2024-04-05"
  "2024-04-06" "2024-04-07" "2024-04-08" "2024-04-09" "2024-04-10"
)

# ── Seleciona 3 índices distintos aleatórios (Fisher-Yates) ──
pick_3_indices() {
  local indices=(0 1 2 3 4)
  for i in 4 3 2 1; do
    j=$((RANDOM % (i + 1)))
    tmp=${indices[$i]}
    indices[$i]=${indices[$j]}
    indices[$j]=$tmp
  done
  echo "${indices[0]} ${indices[1]} ${indices[2]}"
}

# ── Retorna URL de consulta com data opcional aleatória ──────
build_weather_url() {
  local city_url="$1"
  local url="${BASE_URL}/weather?city=${city_url}"

  # 50% de chance de incluir uma data
  if (( RANDOM % 2 == 0 )); then
    local date="${DATES[$((RANDOM % ${#DATES[@]}))]}"
    url="${url}&date=${date}"
    echo "${url}|${date}"
  else
    echo "${url}|sem data"
  fi
}

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

# ── Requisição que gera exceção (422 Unprocessable Entity) ────
EXCEPTION_REQ="${BASE_URL}/weather?date=2024-04-01"

# ── Cidade com mais de 50 caracteres → HTTP 400 ──────────────
BAD_CITY="EstaCidadeTemUmNomeMuitoLongoQueUltrapassaOLimiteDe50Chars"
BAD_REQ_400="${BASE_URL}/weather?city=${BAD_CITY}"

# ── Loop principal ───────────────────────────────────────────
echo ""
echo "========================================"
echo "  Load Test — env: ${ENV}  porta: ${PORT}"
echo "  Iterações: ${ITERATIONS}  sleep: ${SLEEP}s"
echo "========================================"

for ((iter=1; iter<=ITERATIONS; iter++)); do
  echo ""
  echo "── Iteração ${iter}/${ITERATIONS} ─────────────────────"

  # /live e /hello
  do_request "GET /live"  "${BASE_URL}/live"
  do_request "GET /hello" "${BASE_URL}/hello"

  # 3 cidades aleatórias distintas por iteração
  read -r idx0 idx1 idx2 <<< "$(pick_3_indices)"
  for idx in $idx0 $idx1 $idx2; do
    city_name="${CITIES_NAME[$idx]}"
    city_url="${CITIES_URL[$idx]}"

    result="$(build_weather_url "$city_url")"
    url="${result%%|*}"
    date_info="${result##*|}"

    do_request "GET /weather ${city_name} (${date_info})" "$url"
    CITY_COUNT[$idx]=$(( CITY_COUNT[$idx] + 1 ))
  done

  # 1 requisição com erro 400
  do_request "GET /weather cidade longa (→ 400)" "$BAD_REQ_400"

  # 1 requisição que gera exceção (422)
  do_request "GET /weather sem city  (→ 422)" "$EXCEPTION_REQ"

done

TOTAL_CITY_REQS=$(( ITERATIONS * 3 ))

# Encontra o maior contador para normalizar a barra
MAX_COUNT=0
for i in "${!CITIES_NAME[@]}"; do
  (( CITY_COUNT[$i] > MAX_COUNT )) && MAX_COUNT=${CITY_COUNT[$i]}
done

echo ""
echo "========================================"
echo "  Concluído: $((ITERATIONS * 7)) requisições enviadas"
echo "  (${ITERATIONS}×2 infra + ${ITERATIONS}×3 cidades + ${ITERATIONS}×1 erro 400 + ${ITERATIONS}×1 exceção)"
echo "========================================"
echo ""
echo "========================================"
echo "  Relatório — Requisições por Cidade"
echo "========================================"
for i in "${!CITIES_NAME[@]}"; do
  name="${CITIES_NAME[$i]}"
  count=${CITY_COUNT[$i]}
  pct=0
  (( TOTAL_CITY_REQS > 0 )) && pct=$(( count * 100 / TOTAL_CITY_REQS ))

  # Barra proporcional ao maior valor (max 20 chars)
  bar_len=0
  (( MAX_COUNT > 0 )) && bar_len=$(( count * 20 / MAX_COUNT ))
  bar=$(printf '█%.0s' $(seq 1 $bar_len 2>/dev/null))
  (( bar_len == 0 )) && bar="░"

  printf "  %-18s %3d req  (%3d%%)  %s\n" "$name" "$count" "$pct" "$bar"
done
echo "  ──────────────────────────────────────"
printf "  %-18s %3d req  (100%%)\n" "Total" "$TOTAL_CITY_REQS"
echo "========================================"
echo ""
