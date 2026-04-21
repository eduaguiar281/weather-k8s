#!/usr/bin/env bash
# Aplica os Applications do Argo CD no cluster.
#
# Inclui retry automático para o erro de webhook do OpenTelemetry Operator
# ("connection refused") que ocorre quando o Argo tenta aplicar o recurso
# Instrumentation logo após o bootstrap, antes do webhook estar pronto.
#
# Uso:
#   ./scripts/04-apply-argocd-apps.sh            # infra + dev
#   ./scripts/04-apply-argocd-apps.sh --prod     # infra + dev + prod

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
ARGOCD_DIR="$ROOT_DIR/k8s/argocd"

WITH_PROD=false
for arg in "$@"; do
  [[ "$arg" == "--prod" ]] && WITH_PROD=true
done

APPS=(weather-infra weather-api-dev)
$WITH_PROD && APPS+=(weather-api-prod)

# ── Aplicar manifests ──────────────────────────────────────────────────────────
echo "==> Aplicando Applications no Argo CD..."
for app in "${APPS[@]}"; do
  manifest="$ARGOCD_DIR/${app}.yaml"
  if [[ ! -f "$manifest" ]]; then
    echo "    Aviso: $manifest não encontrado; pulando." >&2
    continue
  fi
  kubectl apply -f "$manifest"
done

# ── Aguardar e corrigir erro de webhook OTel ────────────────────────────────────
WEBHOOK_ERR="connection refused"
WAIT_SECONDS=45

echo ""
echo "==> Aguardando ${WAIT_SECONDS}s para o sync inicial..."
sleep "$WAIT_SECONDS"

for app in "${APPS[@]}"; do
  sync_msg=$(kubectl get application "$app" -n argocd \
    -o jsonpath='{.status.conditions[?(@.type=="SyncError")].message}' 2>/dev/null || true)

  if echo "$sync_msg" | grep -q "$WEBHOOK_ERR"; then
    echo ""
    echo "    [$app] Erro de webhook OTel detectado — recriando Application..."
    kubectl delete application "$app" -n argocd --ignore-not-found
    kubectl apply -f "$ARGOCD_DIR/${app}.yaml"
    echo "    [$app] Recriado. Aguardando 30s para novo sync..."
    sleep 30
  fi
done

# ── Status final ───────────────────────────────────────────────────────────────
echo ""
echo "==> Status dos Applications:"
kubectl get application -n argocd

echo ""
echo "✓ Feito. Se algum ainda mostrar OutOfSync, aguarde mais alguns segundos e:"
echo "  kubectl get application -n argocd"
