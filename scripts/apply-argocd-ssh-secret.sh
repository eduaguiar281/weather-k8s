#!/usr/bin/env bash
# Cria o Secret de repositório Git (SSH) do Argo CD sem colar a chave num YAML
# (evita erro de parser nas linhas -----BEGIN... e chaves commitadas por engano).
#
# Uso:
#   ./scripts/apply-argocd-ssh-secret.sh
#   ARGOCD_SSH_KEY=$HOME/.ssh/outra-chave ./scripts/apply-argocd-ssh-secret.sh
#
# Pré-requisito: chave pública registada no GitHub (Deploy key ou SSH da conta).

set -euo pipefail

ARGOCD_SSH_KEY="${ARGOCD_SSH_KEY:-$HOME/.ssh/argocd-weather-k8s}"
REPO_URL="${ARGOCD_REPO_URL:-git@github.com:eduaguiar281/weather-k8s.git}"
SECRET_NAME="${ARGOCD_SSH_SECRET_NAME:-repo-weather-k8s-ssh}"

if [[ ! -f "$ARGOCD_SSH_KEY" ]]; then
  echo "Erro: ficheiro de chave privada não encontrado: $ARGOCD_SSH_KEY" >&2
  exit 1
fi

echo "==> Aplicando Secret ${SECRET_NAME} no namespace argocd (repo: ${REPO_URL})..."

kubectl delete secret "$SECRET_NAME" -n argocd --ignore-not-found

kubectl create secret generic "$SECRET_NAME" \
  -n argocd \
  --from-literal=type=git \
  --from-literal=url="$REPO_URL" \
  --from-file=sshPrivateKey="$ARGOCD_SSH_KEY"

kubectl label secret "$SECRET_NAME" -n argocd argocd.argoproj.io/secret-type=repository --overwrite

echo "==> Reiniciando argocd-repo-server..."
kubectl rollout restart deployment/argocd-repo-server -n argocd

echo ""
echo "✓ Secret aplicado. Confira: kubectl get application -n argocd"
