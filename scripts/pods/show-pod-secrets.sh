#!/usr/bin/env bash
set -eo pipefail

usage() {
  echo "Uso: $0 <app-name> [-n <namespace>]"
  echo ""
  echo "  Busca pods pelo label 'app=<app-name>' e exibe suas secrets."
  echo ""
  echo "Exemplos:"
  echo "  $0 weather-api"
  echo "  $0 weather-api -n weather-dev"
  echo "  $0 alert-agent -n weather-agent"
  exit 1
}

# ---------------------------------------------------------------------------
# Argumentos
# ---------------------------------------------------------------------------
APP_NAME=""
NAMESPACE=""

while [[ $# -gt 0 ]]; do
  case "$1" in
    -n|--namespace)
      NAMESPACE="$2"
      shift 2
      ;;
    -h|--help)
      usage
      ;;
    *)
      if [[ -z "$APP_NAME" ]]; then
        APP_NAME="$1"
        shift
      else
        echo "Argumento inesperado: $1"
        usage
      fi
      ;;
  esac
done

[[ -z "$APP_NAME" ]] && usage

kubectl_ns() {
  if [[ -n "$NAMESPACE" ]]; then
    kubectl "$@" -n "$NAMESPACE"
  else
    kubectl "$@" --all-namespaces
  fi
}

kubectl_in_ns() {
  local ns="$1"
  shift
  kubectl "$@" -n "$ns"
}

# ---------------------------------------------------------------------------
# Busca pods pelo label app=<APP_NAME>
# ---------------------------------------------------------------------------
if [[ -n "$NAMESPACE" ]]; then
  POD_LIST=$(kubectl get pods -n "$NAMESPACE" -l "app=$APP_NAME" \
    -o jsonpath='{range .items[*]}{.metadata.namespace}{"\t"}{.metadata.name}{"\n"}{end}' 2>/dev/null)
else
  POD_LIST=$(kubectl get pods --all-namespaces -l "app=$APP_NAME" \
    -o jsonpath='{range .items[*]}{.metadata.namespace}{"\t"}{.metadata.name}{"\n"}{end}' 2>/dev/null)
fi

if [[ -z "$POD_LIST" ]]; then
  echo "Nenhum pod encontrado com label 'app=$APP_NAME'${NAMESPACE:+ no namespace '$NAMESPACE'}."
  exit 1
fi

POD_COUNT=$(echo "$POD_LIST" | wc -l | tr -d ' ')
echo ""
echo "Encontrado(s) $POD_COUNT pod(s) com app=$APP_NAME"

# ---------------------------------------------------------------------------
# Função que exibe secrets de um pod
# ---------------------------------------------------------------------------
show_secret() {
  local ns="$1"
  local secret="$2"
  echo ""
  echo "    Secret: $secret"
  kubectl get secret "$secret" -n "$ns" \
    -o go-template='{{range $k,$v := .data}}{{printf "        %s = %s\n" $k ($v | base64decode)}}{{end}}' 2>/dev/null \
    || echo "    [secret não encontrada ou sem permissão]"
}

show_pod_secrets() {
  local ns="$1"
  local pod="$2"

  echo ""
  echo "========================================================"
  echo " Pod      : $pod"
  echo " Namespace: $ns"
  echo "========================================================"

  # 1. secretKeyRef
  echo ""
  echo "  >>> Secrets via env (secretKeyRef)"
  echo "  --------------------------------------------------------"
  local env_secrets
  env_secrets=$(kubectl get pod "$pod" -n "$ns" \
    -o jsonpath='{.spec.containers[*].env[*].valueFrom.secretKeyRef.name}' \
    2>/dev/null | tr ' ' '\n' | sort -u)

  if [[ -z "$env_secrets" ]]; then
    echo "  (nenhuma)"
  else
    while IFS= read -r s; do show_secret "$ns" "$s"; done <<< "$env_secrets"
  fi

  # 2. envFrom
  echo ""
  echo "  >>> Secrets via envFrom"
  echo "  --------------------------------------------------------"
  local from_secrets
  from_secrets=$(kubectl get pod "$pod" -n "$ns" \
    -o jsonpath='{.spec.containers[*].envFrom[*].secretRef.name}' \
    2>/dev/null | tr ' ' '\n' | sort -u)

  if [[ -z "$from_secrets" ]]; then
    echo "  (nenhuma)"
  else
    while IFS= read -r s; do show_secret "$ns" "$s"; done <<< "$from_secrets"
  fi

  # 3. volumes
  echo ""
  echo "  >>> Secrets montadas como volumes"
  echo "  --------------------------------------------------------"
  local vol_secrets
  vol_secrets=$(kubectl get pod "$pod" -n "$ns" \
    -o jsonpath='{.spec.volumes[*].secret.secretName}' \
    2>/dev/null | tr ' ' '\n' | sort -u)

  if [[ -z "$vol_secrets" ]]; then
    echo "  (nenhuma)"
  else
    while IFS= read -r s; do show_secret "$ns" "$s"; done <<< "$vol_secrets"
  fi
}

# ---------------------------------------------------------------------------
# Itera sobre os pods encontrados
# ---------------------------------------------------------------------------
while IFS=$'\t' read -r NS POD; do
  [[ -z "$POD" ]] && continue
  show_pod_secrets "$NS" "$POD"
done <<< "$POD_LIST"

echo ""
echo "========================================================"
echo " Concluído."
echo "========================================================"
