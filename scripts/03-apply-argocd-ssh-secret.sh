#!/usr/bin/env bash
# Cria credencial SSH no Argo CD para clonar repos no GitHub via git@...
# Usa secret tipo "repo-creds" com URL-prefix (documentação Argo CD), mais robusto
# do que "repository" só com URL completa em alguns casos.
#
# Uso:
#   ./scripts/apply-argocd-ssh-secret.sh
#   ARGOCD_SSH_KEY=$HOME/.ssh/outra-chave ./scripts/apply-argocd-ssh-secret.sh
#
# Variáveis:
#   ARGOCD_SSH_KEY        Chave privada (sem .pub) — default: ~/.ssh/argocd-weather-k8s
#   ARGOCD_REPO_URL_PREFIX  Prefixo Git SSH — default: git@github.com:eduaguiar281
#                             (tem de fazer prefix-match com git@github.com:user/repo.git)

set -euo pipefail

ARGOCD_SSH_KEY="${ARGOCD_SSH_KEY:-$HOME/.ssh/argocd-weather-k8s}"
# Prefixo: tudo antes de /repo.git → cobre user/weather-k8s.git
ARGOCD_REPO_URL_PREFIX="${ARGOCD_REPO_URL_PREFIX:-git@github.com:eduaguiar281}"
SECRET_NAME="${ARGOCD_SSH_SECRET_NAME:-repo-weather-k8s-ssh-creds}"

if [[ ! -f "$ARGOCD_SSH_KEY" ]]; then
  echo "Erro: ficheiro de chave privada não encontrado: $ARGOCD_SSH_KEY" >&2
  exit 1
fi

bytes=$(wc -c < "$ARGOCD_SSH_KEY" | tr -d ' ')
if [[ "${bytes}" -lt 100 ]]; then
  echo "Erro: ficheiro da chave parece vazio ou inválido (< 100 bytes)." >&2
  exit 1
fi

echo "==> Credencial SSH Argo CD (repo-creds): url prefixo = ${ARGOCD_REPO_URL_PREFIX}"

# Remove credenciais antigas (outro nome / tipo) para evitar conflito
kubectl delete secret repo-weather-k8s-ssh repo-weather-k8s-ssh-creds "$SECRET_NAME" -n argocd --ignore-not-found 2>/dev/null || true

# repo-creds: mesmo prefixo do que o Application usa (ex.: git@github.com:user/repo.git → prefix git@github.com:user)
kubectl create secret generic "$SECRET_NAME" \
  -n argocd \
  --from-literal=type=git \
  --from-literal=url="$ARGOCD_REPO_URL_PREFIX" \
  --from-file=sshPrivateKey="$ARGOCD_SSH_KEY"

kubectl label secret "$SECRET_NAME" -n argocd argocd.argoproj.io/secret-type=repo-creds --overwrite

echo ""
echo "==> Verificação rápida (bytes da chave no Secret):"
kubectl get secret "$SECRET_NAME" -n argocd -o jsonpath='{.data.sshPrivateKey}' | base64 -d | wc -c | xargs echo "  sshPrivateKey (bytes):"

echo "==> Reiniciando argocd-repo-server..."
kubectl rollout status deployment/argocd-repo-server -n argocd --timeout=120s >/dev/null 2>&1 || true
kubectl rollout restart deployment/argocd-repo-server -n argocd

echo ""
echo "✓ Feito. Aguarde ~30s e: kubectl get application -n argocd"
echo "  Se continuar Unknown: kubectl describe application weather-api-dev -n argocd"
