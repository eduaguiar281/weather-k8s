#!/usr/bin/env bash
# Instala cert-manager e OpenTelemetry Operator no cluster Kind.
# O OTel Operator precisa do cert-manager para gerir os certificados dos webhooks.
# Necessário para que o recurso Instrumentation (auto-instrumentation Python) funcione.
#
# Uso:
#   ./scripts/install-otel-operator.sh
#
# Pré-requisito: cluster Kind ativo (kubectl config use-context kind-local).

set -euo pipefail

CERT_MANAGER_URL="${CERT_MANAGER_URL:-https://github.com/cert-manager/cert-manager/releases/latest/download/cert-manager.yaml}"
OPERATOR_URL="${OTEL_OPERATOR_URL:-https://github.com/open-telemetry/opentelemetry-operator/releases/latest/download/opentelemetry-operator.yaml}"

# ── 1. cert-manager ────────────────────────────────────────────────────────────
if kubectl get deployment cert-manager -n cert-manager >/dev/null 2>&1; then
  echo "==> cert-manager já instalado; pulando."
else
  echo "==> Instalando cert-manager..."
  kubectl apply --server-side --force-conflicts -f "$CERT_MANAGER_URL"
  echo "==> Aguardando cert-manager ficar disponível..."
  kubectl wait --for=condition=available deployment/cert-manager \
    -n cert-manager --timeout=300s
  kubectl wait --for=condition=available deployment/cert-manager-webhook \
    -n cert-manager --timeout=300s
  kubectl wait --for=condition=available deployment/cert-manager-cainjector \
    -n cert-manager --timeout=300s
  echo "✓ cert-manager pronto."
fi

# ── 2. OpenTelemetry Operator ──────────────────────────────────────────────────
if kubectl get deployment opentelemetry-operator-controller-manager \
    -n opentelemetry-operator-system >/dev/null 2>&1; then
  echo "==> OpenTelemetry Operator já instalado; pulando."
else
  echo ""
  echo "==> Instalando OpenTelemetry Operator..."
  kubectl apply --server-side --force-conflicts -f "$OPERATOR_URL"
  echo "==> Aguardando o Operator ficar disponível (pode levar 2-3 min)..."
  kubectl wait --for=condition=available deployment/opentelemetry-operator-controller-manager \
    -n opentelemetry-operator-system --timeout=300s
  echo "✓ OpenTelemetry Operator pronto."
fi

# ── 3. Re-sync Argo CD ─────────────────────────────────────────────────────────
echo ""
echo "==> Forçando re-sync das Applications do Argo CD..."
for app in weather-api-dev weather-infra weather-api; do
  kubectl annotate application "$app" -n argocd argocd.argoproj.io/refresh=hard --overwrite 2>/dev/null || true
done

echo ""
echo "✓ Tudo instalado. Aguarde ~30s e verifique:"
echo "  kubectl get application -n argocd"
