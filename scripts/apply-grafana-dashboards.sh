#!/usr/bin/env bash
# Importa dashboards JSON para o Grafana via API REST.
#
# Uso:
#   ./scripts/apply-grafana-dashboards.sh
#   ./scripts/apply-grafana-dashboards.sh /caminho/para/dashboards
#
# Variáveis opcionais:
#   GRAFANA_URL       (padrão: http://localhost:3000)
#   GRAFANA_TOKEN     (se definido, usa Bearer token)
#   GRAFANA_USER      (padrão: admin; usado quando GRAFANA_TOKEN não estiver definido)
#   GRAFANA_PASSWORD  (padrão: admin; usado quando GRAFANA_TOKEN não estiver definido)

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"

DASHBOARDS_DIR="${1:-$ROOT_DIR/grafana/dashboards}"
GRAFANA_URL="${GRAFANA_URL:-http://localhost:3000}"
GRAFANA_API="${GRAFANA_URL%/}/api/dashboards/db"

if ! command -v curl >/dev/null 2>&1; then
  echo "Erro: comando 'curl' não encontrado." >&2
  exit 1
fi

if ! command -v jq >/dev/null 2>&1; then
  echo "Erro: comando 'jq' não encontrado." >&2
  exit 1
fi

if [[ ! -d "$DASHBOARDS_DIR" ]]; then
  echo "Erro: diretório de dashboards não existe: $DASHBOARDS_DIR" >&2
  exit 1
fi

shopt -s nullglob
dashboard_files=("$DASHBOARDS_DIR"/*.json)
shopt -u nullglob

if [[ ${#dashboard_files[@]} -eq 0 ]]; then
  echo "Erro: nenhum arquivo .json encontrado em $DASHBOARDS_DIR" >&2
  exit 1
fi

curl_auth_args=()
if [[ -n "${GRAFANA_TOKEN:-}" ]]; then
  curl_auth_args=(-H "Authorization: Bearer ${GRAFANA_TOKEN}")
  echo "Autenticacao: Bearer token (GRAFANA_TOKEN)"
else
  GRAFANA_USER="${GRAFANA_USER:-admin}"
  GRAFANA_PASSWORD="${GRAFANA_PASSWORD:-admin}"
  curl_auth_args=(-u "${GRAFANA_USER}:${GRAFANA_PASSWORD}")
  echo "Autenticacao: Basic auth (${GRAFANA_USER})"
fi

echo "Grafana URL: $GRAFANA_URL"
echo "Diretorio:   $DASHBOARDS_DIR"
echo ""

success=0
failed=0

for dashboard_path in "${dashboard_files[@]}"; do
  filename="$(basename "$dashboard_path")"

  if ! jq empty "$dashboard_path" >/dev/null 2>&1; then
    echo "✗ $filename: JSON invalido"
    failed=$((failed + 1))
    continue
  fi

  title="$(jq -r '.title // empty' "$dashboard_path")"
  if [[ -z "$title" ]]; then
    title="$filename"
  fi

  payload="$(jq -c '{dashboard: ., overwrite: true}' "$dashboard_path")"

  response="$(curl -sS \
    -w '\n%{http_code}' \
    -X POST "$GRAFANA_API" \
    "${curl_auth_args[@]}" \
    -H "Content-Type: application/json" \
    -d "$payload")"

  http_code="$(printf '%s\n' "$response" | sed -n '$p')"
  response_body="$(printf '%s\n' "$response" | sed '$d')"

  if [[ "$http_code" =~ ^2[0-9][0-9]$ ]]; then
    status="$(printf '%s' "$response_body" | jq -r '.status // "ok"' 2>/dev/null || echo "ok")"
    echo "✓ $filename (${title}) -> ${status}"
    success=$((success + 1))
  else
    message="$(printf '%s' "$response_body" | jq -r '.message // .error // "erro desconhecido"' 2>/dev/null || printf '%s' "$response_body")"
    echo "✗ $filename (${title}) -> HTTP ${http_code}: ${message}"
    failed=$((failed + 1))
  fi
done

echo ""
echo "Resultado: ${success} sucesso(s), ${failed} falha(s)"

if [[ "$failed" -gt 0 ]]; then
  exit 1
fi

echo "Dashboards aplicados com sucesso."
