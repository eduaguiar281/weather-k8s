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
    # rate(process_cpu_time_seconds_total): segundos de CPU / segundo de relógio → núcleos equivalentes
    if metric_name == "cpu_usage":
        cores = f"{v:.3f}".replace(".", ",")
        pct_um_nucleo = f"{(v * 100):.1f}".replace(".", ",")
        return (
            f"≈ {cores} núcleo(s) de CPU em média "
            f"(≈ {pct_um_nucleo}% da capacidade de 1 núcleo; janela da query em [5m])"
        )
    if metric_name == "memory_bytes":
        gib = v / (1024**3)
        mib = v / (1024**2)
        if gib >= 1.0:
            return f"≈ {gib:.2f} GiB".replace(".", ",")
        return f"≈ {mib:.1f} MiB".replace(".", ",")
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
- Para cada evidência vinda do Promethues indique o nome da métrica e o valor obeservado. Caso a métrica não retorne valor mostre "Não encontrado"
- **Inclua todas** as métricas listadas em «Métricas coletadas».
- Para logs: trecho ou padrão que sustenta a hipótese.

### Impacto estimado
[Usuários afetados? Serviço degradado ou indisponível? Severidade real?]

### Próximos passos
1. [Ação imediata mais importante]
2. [Segunda ação]
3. [Verificação adicional se necessário]

## Diretrizes

- Seja direto e objetivo. Desenvolvedores sob pressão não querem texto longo.
- Se os dados forem insuficientes, diga explicitamente o que está faltando.
- Prefira hipóteses concretas a afirmações vagas como "pode ser um problema de performance".
- Se «Métricas coletadas» listar `valor=...` para uma série, esse valor **deve** aparecer na seção **Evidências encontradas** (não omita por brevidade).
- Na seção **Escopo verificado**, use sempre os bullets no formato pedido acima — sem omitir aplicação nem ambiente.
- Quando «Logs coletados» incluir queries LogQL da automação, a subseção **Logs** em **Queries para investigação** deve **reproduzir** essas expressões (ou versões refinadas com filtros adicionais como `|= "texto"` / `| json`), não omitir LogQL.
- Quando houver métricas coletadas, sugira pelo menos uma PromQL; quando houver logs ou queries LogQL no contexto, sugira pelo menos uma LogQL para recuperação de logs.
"""


def format_collected_logql_markdown(log_queries: dict[str, str]) -> str:
    """Anexo com as expressões LogQL usadas em `ContextCollector.collect_logs`."""
    chunks: list[str] = []
    for name in sorted(log_queries.keys()):
        q = log_queries.get(name)
        if not isinstance(q, str) or not q.strip():
            continue
        chunks.append(f"#### `{name}`\n```logql\n{q.strip()}\n```")
    if not chunks:
        return ""
    return (
        "\n---\n\n"
        "### Queries LogQL utilizadas na coleta automática\n\n"
        "Expressões executadas pelo agente para obter os logs listados no contexto:\n\n"
        + "\n\n".join(chunks)
    )


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


def truncate_user_prompt(text: str, max_chars: int) -> tuple[str, bool]:
    """
    Encolhe o prompt do usuário para caber em modelos com contexto pequeno (ex.: n_ctx=4096).
    Mantém o início (alerta + métricas vêm antes dos logs); remove o final se necessário.
    """
    if max_chars <= 0 or len(text) <= max_chars:
        return text, False
    notice = (
        "\n\n---\n*[Contexto truncado: aumente LLM_MAX_USER_PROMPT_CHARS ou o n_ctx do "
        "servidor (LM Studio / llama.cpp) para enviar mais dados.]*\n"
    )
    budget = max_chars - len(notice)
    if budget < 256:
        budget = 256
    return text[:budget].rstrip() + notice, True


def build_user_prompt(
    alert,
    metrics: dict,
    logs: dict,
    related_alerts: list,
    log_queries: dict[str, str] | None = None,
) -> str:
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
        f"(Métricas OTel no Prometheus e logs Loki: `service_name` + `deployment_environment` quando existirem nos labels; fallback Loki por namespace/job.)",
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
            q = (log_queries or {}).get(category)
            if isinstance(q, str) and q.strip():
                lines.append(
                    "  **Query utilizada pela automação (LogQL — reproduza na seção "
                    "«Queries para investigação»):**"
                )
                lines.append(f"```logql\n{q.strip()}\n```")
            if log_lines:
                for line in log_lines[:8]:      # mantém prompt menor para LLMs locais
                    lines.append(f"  {line[:220]}")
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
