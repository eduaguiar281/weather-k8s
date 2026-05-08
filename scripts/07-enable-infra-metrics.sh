#!/usr/bin/env bash
# Habilita coleta de métricas de infraestrutura Kubernetes para o dashboard
# grafana/dashboards/weather-infra.json.
#
# O script:
#   1) Garante conectividade entre o nó Kind e a rede do Compose
#   2) Instala kube-state-metrics no cluster Kind
#   3) Instala cAdvisor no cluster Kind
#   4) Expõe ambos via NodePort no nó Kind
#   5) Atualiza prometheus/prometheus.yml com jobs de scrape
#   6) Reinicia o container do Prometheus (Compose)
#
# Uso:
#   ./scripts/07-enable-infra-metrics.sh
#
# Variáveis opcionais:
#   KIND_NODE            (padrão: local-control-plane)
#   COMPOSE_NETWORK      (padrão: weather-k8s_observability)
#   CADVISOR_NODEPORT    (padrão: 30080)
#   KSM_NODEPORT         (padrão: 30081)

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
PROM_CONFIG="${ROOT_DIR}/prometheus/prometheus.yml"

KIND_NODE="${KIND_NODE:-local-control-plane}"
COMPOSE_NETWORK="${COMPOSE_NETWORK:-weather-k8s_observability}"
CADVISOR_NODEPORT="${CADVISOR_NODEPORT:-30080}"
KSM_NODEPORT="${KSM_NODEPORT:-30081}"

need_cmd() {
  command -v "$1" >/dev/null 2>&1 || {
    echo "Erro: comando '$1' não encontrado no PATH." >&2
    exit 1
  }
}

need_cmd docker
need_cmd kubectl
need_cmd awk
need_cmd mktemp

docker info >/dev/null 2>&1 || {
  echo "Erro: daemon Docker não está acessível." >&2
  exit 1
}

if [[ ! -f "$PROM_CONFIG" ]]; then
  echo "Erro: arquivo não encontrado: $PROM_CONFIG" >&2
  exit 1
fi

echo "==> Verificando nó Kind: $KIND_NODE"
docker inspect "$KIND_NODE" >/dev/null 2>&1 || {
  echo "Erro: container do nó Kind '$KIND_NODE' não encontrado." >&2
  echo "Dica: confirme se o cluster Kind foi criado com nome 'local'." >&2
  exit 1
}

echo "==> Garantindo rede Docker compartilhada ($COMPOSE_NETWORK)..."
if ! docker network inspect "$COMPOSE_NETWORK" >/dev/null 2>&1; then
  # Compatibilidade: em alguns ambientes antigos a rede usada era observability_observability.
  if docker network inspect "observability_observability" >/dev/null 2>&1; then
    COMPOSE_NETWORK="observability_observability"
    echo "    Usando rede legada detectada: $COMPOSE_NETWORK"
  else
    echo "Erro: rede '$COMPOSE_NETWORK' não existe." >&2
    echo "Dica: suba a stack com docker compose up -d e tente novamente." >&2
    exit 1
  fi
fi

if ! docker inspect "$KIND_NODE" --format '{{range .NetworkSettings.Networks}}{{.NetworkID}}{{"\n"}}{{end}}' | \
  grep -q "$(docker network inspect "$COMPOSE_NETWORK" --format '{{.Id}}')"; then
  docker network connect "$COMPOSE_NETWORK" "$KIND_NODE"
  echo "    Nó Kind conectado à rede do Compose."
else
  echo "    Nó Kind já conectado à rede do Compose."
fi

echo "==> Instalando/atualizando kube-state-metrics..."
kubectl apply -k "github.com/kubernetes/kube-state-metrics/examples/standard?ref=v2.13.0"

kubectl apply -f - <<EOF
apiVersion: v1
kind: Service
metadata:
  name: kube-state-metrics-nodeport
  namespace: kube-system
spec:
  type: NodePort
  selector:
    app.kubernetes.io/name: kube-state-metrics
  ports:
    - name: http-metrics
      port: 8080
      targetPort: http-metrics
      nodePort: ${KSM_NODEPORT}
EOF

echo "==> Instalando/atualizando cAdvisor..."
kubectl apply -f - <<EOF
apiVersion: apps/v1
kind: DaemonSet
metadata:
  name: cadvisor
  namespace: kube-system
  labels:
    app: cadvisor
spec:
  selector:
    matchLabels:
      app: cadvisor
  template:
    metadata:
      labels:
        app: cadvisor
    spec:
      hostNetwork: true
      hostPID: true
      tolerations:
        - operator: Exists
      containers:
        - name: cadvisor
          image: gcr.io/cadvisor/cadvisor:v0.49.1
          args:
            - --housekeeping_interval=10s
            - --docker_only=false
            - --store_container_labels=true
          ports:
            - containerPort: 8080
              name: http
          securityContext:
            privileged: true
          resources:
            requests:
              cpu: 100m
              memory: 200Mi
            limits:
              cpu: 300m
              memory: 400Mi
          volumeMounts:
            - name: rootfs
              mountPath: /rootfs
              readOnly: true
            - name: var-run
              mountPath: /var/run
            - name: sys
              mountPath: /sys
              readOnly: true
            - name: docker
              mountPath: /var/lib/docker
              readOnly: true
            - name: containerd
              mountPath: /var/lib/containerd
              readOnly: true
            - name: disk
              mountPath: /dev/disk
              readOnly: true
      volumes:
        - name: rootfs
          hostPath:
            path: /
        - name: var-run
          hostPath:
            path: /var/run
        - name: sys
          hostPath:
            path: /sys
        - name: docker
          hostPath:
            path: /var/lib/docker
        - name: containerd
          hostPath:
            path: /var/lib/containerd
        - name: disk
          hostPath:
            path: /dev/disk
---
apiVersion: v1
kind: Service
metadata:
  name: cadvisor-nodeport
  namespace: kube-system
spec:
  type: NodePort
  selector:
    app: cadvisor
  ports:
    - name: http
      port: 8080
      targetPort: http
      nodePort: ${CADVISOR_NODEPORT}
EOF

echo "==> Aguardando exporters ficarem prontos..."
kubectl rollout status deployment/kube-state-metrics -n kube-system --timeout=120s
kubectl rollout status daemonset/cadvisor -n kube-system --timeout=120s

echo "==> Atualizando jobs de scrape no Prometheus..."
tmp_file="$(mktemp)"
awk '
  /# BEGIN infra-kind-metrics/ {skip=1; next}
  /# END infra-kind-metrics/   {skip=0; next}
  !skip {print}
' "$PROM_CONFIG" > "$tmp_file"

cat >> "$tmp_file" <<EOF

# BEGIN infra-kind-metrics
  # Métricas de objetos Kubernetes (deployments, pods, restarts, etc.)
  - job_name: 'kube-state-metrics-kind'
    metrics_path: /metrics
    static_configs:
      - targets: ['${KIND_NODE}:${KSM_NODEPORT}']

  # Métricas de uso real de CPU/memória por container/pod
  - job_name: 'cadvisor-kind'
    metrics_path: /metrics
    static_configs:
      - targets: ['${KIND_NODE}:${CADVISOR_NODEPORT}']
    metric_relabel_configs:
      - source_labels: [container_label_io_kubernetes_pod_name]
        target_label: pod
      - source_labels: [container_label_io_kubernetes_pod_namespace]
        target_label: namespace
      - source_labels: [container_label_io_kubernetes_container_name]
        target_label: container
# END infra-kind-metrics
EOF

# Evita trocar inode de arquivo bind-mounted (Docker Desktop/WSL pode quebrar o mount ao usar mv).
cat "$tmp_file" > "$PROM_CONFIG"
rm -f "$tmp_file"
# Prometheus no container precisa ler esse arquivo bind-mounted.
chmod 644 "$PROM_CONFIG"

echo "==> Recriando Prometheus do Docker Compose..."
docker compose -f "$ROOT_DIR/docker-compose.yml" up -d --force-recreate prometheus >/dev/null
echo "    Container 'prometheus' recriado."

echo ""
echo "✓ Coleta de métricas de infraestrutura habilitada."
echo "  - kube-state-metrics: ${KIND_NODE}:${KSM_NODEPORT}"
echo "  - cadvisor:           ${KIND_NODE}:${CADVISOR_NODEPORT}"
echo ""
echo "Próximos passos:"
echo "  1) Aguarde 30-60s para o Prometheus raspar as novas séries."
echo "  2) Rode: ./scripts/apply-grafana-dashboards.sh"
echo "  3) Abra o dashboard 'Weather — Infra Kubernetes' no Grafana."
