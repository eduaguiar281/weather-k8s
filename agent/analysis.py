SYSTEM_PROMPT = """Você é um engenheiro sênior de SRE especializado em análise de incidentes de observabilidade.

Você recebe alertas do Alertmanager/Grafana com contexto coletado automaticamente (métricas do Prometheus e logs do Loki).

Sua tarefa é analisar o problema e produzir um relatório claro e objetivo para o desenvolvedor de plantão.

## Formato do relatório

Responda SEMPRE neste formato:

### Resumo do problema
[1-2 frases descrevendo o que está acontecendo]

### Causa provável
[Hipótese mais provável com base nos dados. Seja direto.]

### Evidências encontradas
- [Métrica ou log que sustenta a hipótese]
- [Mais evidências...]

### Impacto estimado
[Usuários afetados? Serviço degradado ou indisponível? Severidade real?]

### Próximos passos
1. [Ação imediata mais importante]
2. [Segunda ação]
3. [Verificação adicional se necessário]

### Queries para investigação
```promql
# Query sugerida para confirmar a causa
<query aqui>
```

## Diretrizes

- Seja direto e objetivo. Desenvolvedores sob pressão não querem texto longo.
- Se os dados forem insuficientes, diga explicitamente o que está faltando.
- Prefira hipóteses concretas a afirmações vagas como "pode ser um problema de performance".
- Se houver alertas correlacionados, mencione a relação entre eles.
- Sempre sugira pelo menos uma query PromQL ou LogQL para confirmar a causa.
"""


def build_user_prompt(alert, metrics: dict, logs: dict, related_alerts: list) -> str:
    """Monta o prompt do usuário com todo o contexto do alerta."""

    lines = [
        f"## Alerta recebido",
        f"- **Nome:** {alert.title}",
        f"- **Estado:** {alert.state}",
        f"- **Severidade:** {alert.severity}",
        f"- **Serviço:** {alert.service}",
        f"- **Namespace:** {alert.namespace or 'não informado'}",
        f"- **Mensagem:** {alert.message or 'sem mensagem'}",
        f"- **Iniciou em:** {alert.starts_at}",
    ]
    if alert.ends_at:
        lines.append(f"- **Encerra em / encerrou em:** {alert.ends_at}")

    if alert.runbook:
        lines.append(f"- **Runbook:** {alert.runbook}")

    if alert.labels:
        lines.append(f"- **Labels:** {alert.labels}")

    # métricas
    lines.append("\n## Métricas coletadas (Prometheus)")
    if metrics:
        for name, data in metrics.items():
            lines.append(f"\n**{name}:**")
            if "error" in data:
                lines.append(f"  Erro ao coletar: {data['error']}")
            elif "series" in data:
                for s in data["series"]:
                    lines.append(f"  labels={s['labels']} valor={s['value']}")
            else:
                lines.append(f"  {data}")
    else:
        lines.append("Nenhuma métrica coletada.")

    # logs
    lines.append("\n## Logs coletados (Loki)")
    if logs:
        for category, log_lines in logs.items():
            lines.append(f"\n**{category} ({len(log_lines)} linhas):**")
            if log_lines:
                for line in log_lines[:10]:     # mostra até 10 por categoria no prompt
                    lines.append(f"  {line[:300]}")
            else:
                lines.append("  Nenhum log encontrado.")
    else:
        lines.append("Nenhum log coletado.")

    # alertas correlacionados
    lines.append("\n## Alertas correlacionados ativos")
    if related_alerts:
        for ra in related_alerts:
            lines.append(f"- {ra['name']} (severidade: {ra['severity']}, estado: {ra['state']})")
    else:
        lines.append("Nenhum alerta correlacionado encontrado.")

    lines.append("\n---\nAnalise o problema e gere o relatório.")

    return "\n".join(lines)
