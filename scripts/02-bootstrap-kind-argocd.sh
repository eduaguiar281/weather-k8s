#!/usr/bin/env bash
# Bootstrap completo do cluster local:
#   1. Cluster Kind
#   2. cert-manager        (pré-requisito do OpenTelemetry Operator)
#   3. OpenTelemetry Operator  (pré-requisito para o recurso Instrumentation)
#   4. Argo CD
#
# Compatível com macOS e Linux (incl. WSL2), desde que Docker, kind e kubectl estejam no PATH.
#
# Uso:
#   ./scripts/bootstrap-kind-argocd.sh
#   CLUSTER_NAME=local ARGOCD_VERSION=v2.13.4 ./scripts/bootstrap-kind-argocd.sh
#
# Variáveis de ambiente:
#   CLUSTER_NAME     Nome do cluster Kind (padrão: local)
#   ARGOCD_VERSION   Tag do repositório argo-cd (ex.: v2.13.4) ou "stable"

set -euo pipefail

CLUSTER_NAME="${CLUSTER_NAME:-local}"
ARGOCD_VERSION="${ARGOCD_VERSION:-stable}"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
KIND_CONFIG="${ROOT_DIR}/kind/cluster-config.yaml"

die() {
  echo "Erro: $*" >&2
  exit 1
}

need_cmd() {
  command -v "$1" >/dev/null 2>&1 || die "Comando '$1' não encontrado. Instale e coloque no PATH."
}

need_cmd docker
need_cmd kind
need_cmd kubectl

docker info >/dev/null 2>&1 || die "O daemon do Docker não está acessível. Inicie o Docker e tente de novo."

if [[ ! -f "$KIND_CONFIG" ]]; then
  die "Arquivo de configuração Kind não encontrado: $KIND_CONFIG"
fi

echo "==> Cluster Kind: ${CLUSTER_NAME}"

if kind get clusters 2>/dev/null | grep -qx "${CLUSTER_NAME}"; then
  echo "    Cluster '${CLUSTER_NAME}' já existe; pulando kind create cluster."
else
  kind create cluster --name "${CLUSTER_NAME}" --config "${KIND_CONFIG}"
fi

kubectl config use-context "kind-${CLUSTER_NAME}" >/dev/null

# ── cert-manager ───────────────────────────────────────────────────────────────
CERT_MANAGER_URL="${CERT_MANAGER_URL:-https://github.com/cert-manager/cert-manager/releases/latest/download/cert-manager.yaml}"
if kubectl get deployment cert-manager -n cert-manager >/dev/null 2>&1; then
  echo "==> cert-manager: já instalado; pulando."
else
  echo "==> Instalando cert-manager..."
  kubectl apply --server-side --force-conflicts -f "$CERT_MANAGER_URL"
  kubectl wait --for=condition=available deployment/cert-manager           -n cert-manager --timeout=300s
  kubectl wait --for=condition=available deployment/cert-manager-webhook   -n cert-manager --timeout=300s
  kubectl wait --for=condition=available deployment/cert-manager-cainjector -n cert-manager --timeout=300s
  echo "✓ cert-manager pronto."
fi

# ── OpenTelemetry Operator ─────────────────────────────────────────────────────
OTEL_OPERATOR_URL="${OTEL_OPERATOR_URL:-https://github.com/open-telemetry/opentelemetry-operator/releases/latest/download/opentelemetry-operator.yaml}"
if kubectl get deployment opentelemetry-operator-controller-manager -n opentelemetry-operator-system >/dev/null 2>&1; then
  echo "==> OpenTelemetry Operator: já instalado; pulando."
else
  echo "==> Instalando OpenTelemetry Operator..."
  kubectl apply --server-side --force-conflicts -f "$OTEL_OPERATOR_URL"
  kubectl wait --for=condition=available deployment/opentelemetry-operator-controller-manager \
    -n opentelemetry-operator-system --timeout=300s
  echo "✓ OpenTelemetry Operator pronto."
fi

# ── Argo CD ────────────────────────────────────────────────────────────────────
if [[ "$ARGOCD_VERSION" == "stable" ]]; then
  MANIFEST_URL="https://raw.githubusercontent.com/argoproj/argo-cd/stable/manifests/install.yaml"
else
  MANIFEST_URL="https://raw.githubusercontent.com/argoproj/argo-cd/${ARGOCD_VERSION}/manifests/install.yaml"
fi

if kubectl get deployment argocd-server -n argocd >/dev/null 2>&1 &&
  kubectl get crd applicationsets.argoproj.io >/dev/null 2>&1; then
  echo "==> Argo CD: já instalado (argocd-server + CRD ApplicationSet); pulando."
else
  echo "==> Instalando Argo CD (${ARGOCD_VERSION})..."
  kubectl get namespace argocd >/dev/null 2>&1 || kubectl create namespace argocd
  # apply clássico excede o limite de tamanho de metadata.annotations em CRDs grandes;
  # server-side apply evita a anotação kubectl.kubernetes.io/last-applied-configuration.
  kubectl apply --server-side --force-conflicts -n argocd -f "$MANIFEST_URL"
fi

echo "==> Aguardando o Argo CD ficar disponível..."
kubectl wait --for=condition=available deployment/argocd-server -n argocd --timeout=300s

echo ""
echo "==> Senha inicial do usuário admin (guarde em local seguro):"
if kubectl get secret argocd-initial-admin-secret -n argocd >/dev/null 2>&1; then
  kubectl -n argocd get secret argocd-initial-admin-secret -o jsonpath="{.data.password}" | base64 -d
  echo ""
else
  echo "    (secret argocd-initial-admin-secret ainda não encontrado — aguarde alguns segundos e execute:)"
  echo "    kubectl -n argocd get secret argocd-initial-admin-secret -o jsonpath='{.data.password}' | base64 -d && echo"
fi

echo ""
echo "==> Acesso à UI (em outro terminal):"
echo "    kubectl port-forward svc/argocd-server -n argocd 8080:443"
echo "    Abra https://localhost:8080 (usuário: admin; senha acima; aceite o certificado autofirmado)."
echo ""
echo "✓ Bootstrap concluído."
