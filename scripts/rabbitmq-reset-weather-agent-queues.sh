#!/usr/bin/env bash
# Elimina filas declaradas pelo alert-agent para o próximo startup recriá-las
# (útil quando `weather.agent.analysis` já existe sem x-single-active-consumer e o
# publisher falha com PRECONDITION_FAILED).
#
# Uso (RabbitMQ a correr na stack Docker deste repo — Management em :15672):
#   chmod +x scripts/rabbitmq-reset-weather-agent-queues.sh
#   ./scripts/rabbitmq-reset-weather-agent-queues.sh
#
# Variáveis opcionais: RABBITMQ_MGMT_HOST (default 127.0.0.1:15672), RABBITMQ_ADMIN_USER, RABBITMQ_ADMIN_PASS
set -euo pipefail

MGMT_HOST="${RABBITMQ_MGMT_HOST:-127.0.0.1:15672}"
USER_="${RABBITMQ_ADMIN_USER:-guest}"
PASS_="${RABBITMQ_ADMIN_PASS:-guest}"

delete_queue_if_present() {
  local name="$1"
  local code
  code="$(
    curl -s -o /dev/null -w "%{http_code}" \
      -u "${USER_}:${PASS_}" \
      -X DELETE \
      "http://${MGMT_HOST}/api/queues/%2f/${name}"
  )"
  if [[ "$code" == "204" ]]; then
    echo "Eliminada fila / : ${name}"
  elif [[ "$code" == "404" ]]; then
    echo "(ignorado) fila já inexistente: ${name}"
  else
    echo "Aviso: DELETE ${name} HTTP ${code} — verifique se o RabbitMQ Management está disponível (${MGMT_HOST})" >&2
  fi
}

echo "==> RabbitMQ (${MGMT_HOST}) — remover filas do alert-agent antes de rollout com SAC/fila única"
for q in \
  weather.agent.analysis \
  weather.agent.analysis.dlq \
  weather.agent.resolved \
  weather.agent.resolved.dlq; do
  delete_queue_if_present "$q"
done
echo "==> Ao arrancar o alert-agent actualizado, estas filas serão recreadas pela topologia em código."
