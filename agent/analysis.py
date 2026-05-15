from __future__ import annotations

from dataclasses import dataclass, field


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


DEFAULT_LABEL_KEYS: tuple[str, ...] = (
    "alertname",
    "severity",
    "namespace",
    "service_name",
    "deployment_environment",
    "environment",
    "env",
    "stage",
    "job",
    "service",
    "app",
    "app_name",
    "pod",
    "instance",
    "container",
)


def parse_label_allowlist_csv(raw: str) -> frozenset[str]:
    """Converte CSV de env em conjunto; string vazia → defaults."""
    parts = [p.strip() for p in (raw or "").split(",") if p.strip()]
    return frozenset(parts) if parts else frozenset(DEFAULT_LABEL_KEYS)


def _filter_labels_line(labels: dict[str, str], allowlist: frozenset[str]) -> str:
    """Uma linha markdown com labels prioritários; conta omitidos."""
    if not labels:
        return ""
    picked: list[str] = []
    omitted = 0
    for k in sorted(labels.keys()):
        if k in allowlist:
            picked.append(f"{k}={labels[k]}")
        else:
            omitted += 1
    if not picked and omitted:
        return (
            f"- **Labels:** ({omitted} labels omitidos do prompt; use o alerta/fonte bruta se precisar de todos.)"
        )
    line = "- **Labels (prioridade SRE):** " + ", ".join(picked)
    if omitted:
        line += f" — *+{omitted} outros labels omitidos do prompt*"
    return line


def _compact_metric_labels(labels: dict, allowlist: frozenset[str]) -> str:
    if not isinstance(labels, dict):
        return str(labels)
    parts: list[str] = []
    omitted = 0
    for k in sorted(labels.keys()):
        sk = str(k)
        if sk in allowlist:
            parts.append(f"{sk}={labels[k]}")
        else:
            omitted += 1
    s = "{" + ", ".join(parts) + "}"
    if omitted:
        s += f" (+{omitted} labels omitidos)"
    return s


@dataclass(frozen=True)
class UserPromptOptions:
    compact_queries: bool = True
    max_log_lines_per_category: int = 8
    max_log_line_chars: int = 220
    label_keys_allowlist: frozenset[str] = field(
        default_factory=lambda: frozenset(DEFAULT_LABEL_KEYS)
    )


DEFAULT_USER_PROMPT_OPTIONS = UserPromptOptions()


def _format_queries_index(
    metrics: dict,
    log_queries: dict[str, str] | None,
) -> str:
    """Uma única secção com todas as PromQL/LogQL (evita repetir sob cada bloco)."""
    chunks: list[str] = [
        "## Queries utilizadas na coleta (referência)",
        "",
        "As expressões completas também são anexadas automaticamente ao markdown final "
        "após a análise; use os nomes abaixo para correlacionar com métricas e logs.",
        "",
    ]
    prom = False
    for name in sorted(metrics.keys()):
        data = metrics[name]
        if not isinstance(data, dict):
            continue
        q = data.get("query")
        if not isinstance(q, str) or not q.strip():
            continue
        prom = True
        chunks.append(f"### PromQL · `{name}`")
        chunks.append("```promql")
        chunks.append(q.strip())
        chunks.append("```")
        chunks.append("")
    logq = False
    for name in sorted((log_queries or {}).keys()):
        q = (log_queries or {}).get(name)
        if not isinstance(q, str) or not q.strip():
            continue
        logq = True
        chunks.append(f"### LogQL · `{name}`")
        chunks.append("```logql")
        chunks.append(q.strip())
        chunks.append("```")
        chunks.append("")
    if not prom and not logq:
        return ""
    return "\n".join(chunks).rstrip()


def _build_metrics_section(
    metrics: dict,
    *,
    compact_queries: bool,
    allowlist: frozenset[str],
) -> str:
    lines: list[str] = ["\n## Métricas coletadas (Prometheus)"]
    if not metrics:
        lines.append("Nenhuma métrica coletada.")
        return "\n".join(lines)

    for name, data in metrics.items():
        lines.append(f"\n**{name}:**")
        q = data.get("query") if isinstance(data, dict) else None
        if not compact_queries and isinstance(q, str) and q.strip():
            lines.append(
                "  **Query utilizada pela automação (PromQL — reproduza no relatório ou cite o nome):**"
            )
            lines.append(f"```promql\n{q.strip()}\n```")
        if isinstance(data, dict) and "error" in data:
            lines.append(f"  Erro ao coletar: {data['error']}")
        elif isinstance(data, dict) and "series" in data:
            lines.append(
                "  **Valores (obrigatório na seção Evidências encontradas — copie cada valor abaixo):**"
            )
            for s in data["series"]:
                q_str = q if isinstance(q, str) else None
                human = _humanize_prometheus_value(name, s["value"], q_str)
                val = human if human is not None else s["value"]
                lbl = _compact_metric_labels(s.get("labels") or {}, allowlist)
                lines.append(f"  - labels={lbl} valor={val}")
        else:
            lines.append(f"  {data}")
    return "\n".join(lines)


def _build_logs_section(
    logs: dict,
    log_queries: dict[str, str] | None,
    *,
    compact_queries: bool,
    max_lines_per_category: int,
    max_line_chars: int,
) -> str:
    lines: list[str] = ["\n## Logs coletados (Loki)"]
    if not logs:
        lines.append("Nenhum log coletado.")
        return "\n".join(lines)

    cap = max(0, max_lines_per_category)
    for category, log_lines in logs.items():
        lines.append(f"\n**{category} ({len(log_lines)} linhas brutas na coleta):**")
        if not compact_queries:
            q = (log_queries or {}).get(category)
            if isinstance(q, str) and q.strip():
                lines.append(
                    "  **Query utilizada pela automação (LogQL — no relatório cite só o nome "
                    "da categoria, ex.: `errors`; a expressão completa segue no anexo markdown):**"
                )
                lines.append(f"```logql\n{q.strip()}\n```")
        if log_lines and cap > 0:
            for line in log_lines[:cap]:
                lines.append(f"  {line[:max_line_chars]}")
        elif not log_lines:
            lines.append("  Nenhum log encontrado.")
        else:
            lines.append("  (amostras omitidas por limite de contexto)")
    return "\n".join(lines)


def _build_header(alert, allowlist: frozenset[str], *, omit_labels: bool) -> str:
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
        "## Alerta recebido",
        f"- **Nome:** {alert.title}",
        f"- **Estado:** {alert.state}",
        f"- **Severidade:** {alert.severity}",
        "",
        "### Escopo que você deve mencionar na análise",
        "(Métricas OTel no Prometheus e logs Loki: `service_name` + `deployment_environment` quando existirem nos labels; fallback Loki por namespace/job.)",
        f"- **Aplicação verificada:** `{app}` (labels job / service / app)",
        f"- **Ambiente / contexto verificado:** {env_human}",
        f"- **Namespace (filtro nas queries quando presente):** `{ns_detail}`",
        "",
        f"- **Mensagem:** {alert.message or 'sem mensagem'}",
        f"- **Iniciou em:** {alert.starts_at}",
    ]
    if alert.ends_at:
        lines.append(f"- **Encerra em / encerrou em:** {alert.ends_at}")

    if alert.runbook:
        lines.append(f"- **Runbook:** {alert.runbook}")

    if alert.labels and not omit_labels:
        lbl = _filter_labels_line(alert.labels, allowlist)
        if lbl:
            lines.append(lbl)
    elif alert.labels and omit_labels:
        lines.append(
            "- **Labels:** *omitidos por limite de contexto — ver fonte do alerta/Grafana.*"
        )

    return "\n".join(lines)


def _build_related_section(related_alerts: list) -> str:
    lines = ["\n## Alertas correlacionados ativos"]
    if related_alerts:
        for ra in related_alerts:
            lines.append(
                f"- {ra['name']} (severidade: {ra['severity']}, estado: {ra['state']})"
            )
    else:
        lines.append("Nenhum alerta correlacionado encontrado.")
    return "\n".join(lines)


FOOTER = "\n---\nAnalise o problema e gere o relatório."


@dataclass
class _PromptSections:
    header: str
    queries_index: str
    metrics: str
    logs: str
    related: str
    footer: str

    def join(self) -> str:
        parts: list[str] = [self.header]
        if self.queries_index.strip():
            parts.append("\n" + self.queries_index)
        parts.extend([self.metrics, self.logs, self.related, self.footer])
        return "\n".join(parts)


def _assemble_sections(
    alert,
    metrics: dict,
    logs: dict,
    related_alerts: list,
    log_queries: dict[str, str] | None,
    opts: UserPromptOptions,
    *,
    log_lines_per_category: int | None = None,
    omit_header_labels: bool = False,
    minimal_queries_index: bool = False,
) -> _PromptSections:
    allow = opts.label_keys_allowlist
    lines_cap = (
        log_lines_per_category
        if log_lines_per_category is not None
        else opts.max_log_lines_per_category
    )

    idx = ""
    if opts.compact_queries and not minimal_queries_index:
        idx = _format_queries_index(metrics, log_queries)
    elif opts.compact_queries and minimal_queries_index:
        idx = (
            "## Queries utilizadas na coleta (referência)\n\n"
            "*Expressões completas omitidas por limite de contexto — repita no anexo markdown "
            "«Queries PromQL/LogQL utilizadas na coleta automática» ao final da resposta.*"
        )

    return _PromptSections(
        header=_build_header(alert, allow, omit_labels=omit_header_labels),
        queries_index=idx,
        metrics=_build_metrics_section(
            metrics,
            compact_queries=opts.compact_queries,
            allowlist=allow,
        ),
        logs=_build_logs_section(
            logs,
            log_queries,
            compact_queries=opts.compact_queries,
            max_lines_per_category=lines_cap,
            max_line_chars=opts.max_log_line_chars,
        ),
        related=_build_related_section(related_alerts),
        footer=FOOTER,
    )


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
- Para cada evidência vinda do Prometheus indique o nome da métrica e o valor observado. Caso a métrica não retorne valor mostre "Não encontrado"
- **Inclua todas** as métricas listadas em «Métricas coletadas».
- Para logs: trecho ou padrão que sustenta a hipótese.

### Impacto estimado
[Usuários afetados? Serviço degradado ou indisponível? Severidade real?]

### Próximos passos
- Máximo **3** itens numerados. Uma linha curta por item. Omita a secção inteira se não houver ação clara.
- Cite investigações apenas pelos **nomes** já usados no contexto (métricas: ex. `cpu_usage`, `http_latency_p99`; logs: ex. `errors`, `exceptions`). Uma referência = um identificador entre crases; **sem** prefixo «PromQL ·» ou «LogQL ·» com a expressão completa.
- **Proibido** nesta secção: expressões PromQL/LogQL completas; blocos de código; selectors `{label="..."}`; funções tipo `rate()`, `histogram_quantile()`, `sum()`.
- Para aprofundar, prefira sempre o que **já foi calculado** na coleta. Só mencione métricas OTel «cruas» se faltar dado essencial e for inequívoco que não está coberto pelos nomes coletados.
1. [Ação imediata]
2. [Segunda ação, se necessário]
3. [Terceira ação, se necessário]

**Não** inclua subsecções ou listas adicionais só para repetir queries. As expressões completas aparecem em «Queries utilizadas na coleta (referência)» no contexto **e** no anexo markdown **Queries PromQL/LogQL utilizadas na coleta automática** após a sua resposta.

## Diretrizes

- Limite o relatório a **~250–1000 palavras**; frases curtas e bullets objetivos.
- Seja direto e objetivo. Desenvolvedores sob pressão não querem texto longo.
- **Não duplique conteúdo:** não repita a mesma investigação em mais de um lugar; não recopie o anexo de queries no corpo do relatório.
- Exceção mínima: pode citar **uma** linha de filtro *nova* (ex.: `|= "trace_id"`) se for refinamento explícito — não repita queries já fornecidas.
- **Evite** (ruim): listar várias vezes o mesmo selector em «Próximos passos» e ainda listar de novo as mesmas expressões. **Faça** (bom): «Correlacionar `http_latency_p99` com `cpu_usage` e revisar amostras em `errors` no Loki.»
- Se os dados forem insuficientes, diga explicitamente o que está faltando.
- Prefira hipóteses concretas a afirmações vagas como "pode ser um problema de performance".
- Se «Métricas coletadas» listar `valor=...` para uma série, esse valor **deve** aparecer na seção **Evidências encontradas** (não omita por brevidade).
- Na seção **Escopo verificado**, use sempre os bullets no formato pedido acima — sem omitir aplicação nem ambiente.
- Quando houver métricas coletadas, pelo menos um passo deve referenciar o **nome** de uma métrica listada; quando houver logs/queries LogQL no contexto, pelo menos um passo deve referenciar o **nome** de uma categoria (`errors`, `exceptions`, etc.).
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


def truncate_user_prompt_sections(
    alert,
    metrics: dict,
    logs: dict,
    related_alerts: list,
    log_queries: dict[str, str] | None,
    opts: UserPromptOptions,
    max_chars: int,
) -> tuple[str, bool]:
    """
    Aplica orçamento: reduz primeiro linhas de log por categoria, depois índice de queries,
    depois labels no cabeçalho; por último truncamento em cauda (compatível com o antigo).
    """
    if max_chars <= 0:
        text = _assemble_sections(
            alert,
            metrics,
            logs,
            related_alerts,
            log_queries,
            opts,
        ).join()
        return text, False

    for n in range(opts.max_log_lines_per_category, -1, -1):
        sec = _assemble_sections(
            alert,
            metrics,
            logs,
            related_alerts,
            log_queries,
            opts,
            log_lines_per_category=n if n > 0 else 0,
            omit_header_labels=False,
            minimal_queries_index=False,
        )
        t = sec.join()
        if len(t) <= max_chars:
            return t, False

    for minimal_q in (False, True):
        sec = _assemble_sections(
            alert,
            metrics,
            logs,
            related_alerts,
            log_queries,
            opts,
            log_lines_per_category=0,
            omit_header_labels=False,
            minimal_queries_index=minimal_q,
        )
        t = sec.join()
        if len(t) <= max_chars:
            return t, False

    sec = _assemble_sections(
        alert,
        metrics,
        logs,
        related_alerts,
        log_queries,
        opts,
        log_lines_per_category=0,
        omit_header_labels=True,
        minimal_queries_index=True,
    )
    t = sec.join()
    if len(t) <= max_chars:
        return t, True

    return truncate_user_prompt(t, max_chars)


def build_user_prompt(
    alert,
    metrics: dict,
    logs: dict,
    related_alerts: list,
    log_queries: dict[str, str] | None = None,
    *,
    opts: UserPromptOptions | None = None,
) -> str:
    """Monta o prompt do usuário com todo o contexto do alerta."""
    o = opts or DEFAULT_USER_PROMPT_OPTIONS
    return _assemble_sections(
        alert,
        metrics,
        logs,
        related_alerts,
        log_queries,
        o,
    ).join()

