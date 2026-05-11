def _humanize_prometheus_value(
    metric_name: str, raw, query: str | None
) -> str | None:
    """Formata valores conhecidos para leitura (pt-BR: vírgula decimal)."""
    if raw is None:
        return None
    try:
        v = float(raw)
    except (TypeError, ValueError):
        return None
    if metric_name == "http_error_rate":
        return f"{(v * 100):.1f} %".replace(".", ",")
    if metric_name == "http_latency_p99":
        q = (query or "").lower()
        if "milliseconds" in q or "millisecond" in q:
            ms = v
        elif "seconds_bucket" in q or "_seconds" in q:
            ms = v * 1000
        else:
            ms = v
        return f"{ms:.1f} ms".replace(".", ",")
    return None


SYSTEM_PROMPT = """Você é um engenheiro sênior de SRE especializado em análise de incidentes de observabilidade.

Você recebe alertas do Alertmanager/Grafana com contexto coletado automaticamente (métricas do Prometheus e logs do Loki).

Sua tarefa é analisar o problema e produzir um relatório claro e objetivo para o desenvolvedor de plantão.

## Formato do relatório

Responda SEMPRE neste formato:

### Escopo verificado
- **Aplicação analisada:** [valor exato coletado do contexto, ex.: job/serviço]
- **Ambiente analisado:** [environment/env/stage dos labels OU, se inexistentes, declare o namespace/cluster usado como contexto espacial OU que não há metadado suficiente]

### Resumo do problema
[1-2 frases descrevendo o que está acontecendo]

### Causa provável
[Hipótese mais provável com base nos dados. Seja direto.]

### Evidências encontradas
- Para cada evidência **vinda** do Prometheus: indique o **nome** da métrica (ex.: `cpu_usage`), a **PromQL** usada na coleta (reproduza o bloco de «Métricas coletadas») e o **valor observado** — use o texto das linhas `valor=` (já humanizado para `http_error_rate` como percentual e `http_latency_p99` em ms; demais métricas: copie o número literal) e `labels=` quando existirem. **Não** cite só nome + query sem o valor.
- Para logs: trecho ou padrão que sustenta a hipótese.

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
- Se «Métricas coletadas» listar `valor=...` para uma série, esse valor **deve** aparecer na seção **Evidências encontradas** (não omita por brevidade).
- Na seção **Escopo verificado**, use sempre os bullets no formato pedido acima — sem omitir aplicação nem ambiente.
- Sempre sugira pelo menos uma query PromQL ou LogQL para confirmar a causa.
"""


def format_collected_promql_markdown(metrics: dict) -> str:
    """Anexo com as expressões PromQL usadas em `ContextCollector.collect_metrics`."""
    chunks: list[str] = []
    for name in sorted(metrics.keys()):
        data = metrics[name]
        if not isinstance(data, dict):
            continue
        q = data.get("query")
        if not isinstance(q, str) or not q.strip():
            continue
        chunks.append(f"#### `{name}`\n```promql\n{q.strip()}\n```")
    if not chunks:
        return ""
    return (
        "\n---\n\n"
        "### Queries PromQL utilizadas na coleta automática\n\n"
        "Expressões executadas pelo agente para obter as métricas listadas no contexto:\n\n"
        + "\n\n".join(chunks)
    )


def build_user_prompt(alert, metrics: dict, logs: dict, related_alerts: list) -> str:
    """Monta o prompt do usuário com todo o contexto do alerta."""

    app = alert.service
    if alert.environment:
        env_human = alert.environment
    elif alert.namespace:
        env_human = (
            "não há label environment/env/stage — contexto espacial do escopo = "
            f"namespace `{alert.namespace}`"
        )
    else:
        env_human = "não identificado (sem environment/env/stage nem namespace nos labels)"

    ns_detail = alert.namespace or "não informado"

    lines = [
        f"## Alerta recebido",
        f"- **Nome:** {alert.title}",
        f"- **Estado:** {alert.state}",
        f"- **Severidade:** {alert.severity}",
        f"",
        f"### Escopo que você deve mencionar na análise",
        f"(Métricas Prometheus e logs Loki foram filtrados com job/serviço = aplicação e namespace quando existir.)",
        f"- **Aplicação verificada:** `{app}` (labels job / service / app)",
        f"- **Ambiente / contexto verificado:** {env_human}",
        f"- **Namespace (filtro nas queries quando presente):** `{ns_detail}`",
        f"",
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
            q = data.get("query")
            if q:
                lines.append("  **Query utilizada pela automação (PromQL — reproduza no relatório):**")
                lines.append(f"```promql\n{q.strip()}\n```")
            if "error" in data:
                lines.append(f"  Erro ao coletar: {data['error']}")
            elif "series" in data:
                lines.append(
                    "  **Valores (obrigatório na seção Evidências encontradas — copie cada valor abaixo):**"
                )
                for s in data["series"]:
                    q_str = q if isinstance(q, str) else None
                    human = _humanize_prometheus_value(name, s["value"], q_str)
                    val = human if human is not None else s["value"]
                    lines.append(f"  - labels={s['labels']} valor={val}")
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
