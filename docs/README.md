# Documentação de Observabilidade

Este diretório concentra a documentação necessária para **replicar, em escala organizacional, o
modelo de observabilidade validado na POC deste repositório** (`weather-api`).

O objetivo é que qualquer squad da organização consiga entregar uma aplicação em produção
com **traces, métricas e logs correlacionados**, com **mínima alteração de código**, usando
auto-instrumentação via OpenTelemetry Operator.

---

## Índice

| Documento | Para quem | Quando ler |
|-----------|-----------|------------|
| [`observability-playbook.md`](./observability-playbook.md) | Time de Plataforma e tech leads de squad | Ponto de partida. Descreve a arquitetura alvo, responsabilidades e passo a passo completo para replicar o modelo. |
| [`instrumentation-patterns.md`](./instrumentation-patterns.md) | Arquitetos, SREs, tech leads | Para entender **Init Container** vs **Sidecar Container** no contexto OTel: o que cada um resolve, quando usar, quando combinar. |
| [`stacks/python.md`](./stacks/python.md) | Desenvolvedores e squads Python | Checklist prático para habilitar observabilidade em uma app Python. |
| [`stacks/nodejs.md`](./stacks/nodejs.md) | Desenvolvedores e squads Node.js | Checklist prático para habilitar observabilidade em uma app Node.js. |
| [`observability-sidecar-pattern.md`](./observability-sidecar-pattern.md) | Referência histórica | Documento original da POC (Python + FastAPI + psycopg2). Mantido como referência detalhada da prova de conceito. |

---

## Premissas (o que o documento NÃO cobre)

O playbook assume que a organização **já possui**:

- Clusters Kubernetes operacionais em cada cloud;
- **ArgoCD** instalado e configurado nesses clusters (GitOps é o meio de entrega);
- **Grafana, Loki e Jaeger** disponíveis (gerenciados ou self-hosted);
- **Promtail** como DaemonSet de coleta de logs (cobrimos o que precisa ser ajustado na configuração existente);
- Registry de imagens Docker com autenticação configurada no cluster;
- Times usando **Azure DevOps Repos** para versionar código e manifests.

Se algum desses itens ainda não existir, trate como pré-requisito resolvido fora deste playbook.

---

## Leitura recomendada

1. Leia primeiro [`observability-playbook.md`](./observability-playbook.md) de ponta a ponta.
2. Em seguida, mergulhe em [`instrumentation-patterns.md`](./instrumentation-patterns.md) para tomar a decisão arquitetural Init vs Sidecar consciente.
3. Use o guia da sua stack (`stacks/python.md` ou `stacks/nodejs.md`) como checklist durante o onboarding da primeira aplicação.
