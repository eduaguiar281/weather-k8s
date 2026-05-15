import socket
from pathlib import Path
from urllib.parse import quote, urlparse, urlunparse

from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

_AGENT_DIR = Path(__file__).resolve().parent


def _rewrite_host_docker_internal_if_dns_fails(url: str) -> str:
    """host.docker.internal só existe dentro de Docker típico; no host pode não resolver."""
    if not url.strip() or "host.docker.internal" not in url:
        return url
    parsed = urlparse(url)
    if (parsed.hostname or "").lower() != "host.docker.internal":
        return url
    try:
        socket.getaddrinfo(parsed.hostname, None)
        return url
    except socket.gaierror:
        pass
    auth = ""
    if parsed.username is not None:
        auth = quote(parsed.username, safe="")
        if parsed.password is not None:
            auth += ":" + quote(parsed.password, safe="")
        auth += "@"
    netloc = f"{auth}127.0.0.1"
    if parsed.port is not None:
        netloc += f":{parsed.port}"
    return urlunparse(
        (
            parsed.scheme,
            netloc,
            parsed.path,
            parsed.params,
            parsed.query,
            parsed.fragment,
        )
    )


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=str(_AGENT_DIR / ".env"),
        env_file_encoding="utf-8",
        # ENV, DEBUG, etc. usados só via os.getenv / launch.json — não fazem parte do modelo
        extra="ignore",
    )

    env: str = "prod"

    grafana_url: str = "http://grafana:3000"
    grafana_token: str = ""                  # token da service account (glsa_...)

    # configuração da LLM (provider-agnóstico)
    llm_provider: str = "anthropic"          # anthropic | openai
    llm_model: str = "claude-sonnet-4-20250514"
    llm_api_key: str = ""                    # chave da API (anthropic/openai)
    llm_base_url: str = ""                   # base URL customizada (LM Studio, proxies, etc.)
    # Limite de caracteres do prompt do usuário (métricas + logs no texto enviado à LLM).
    # 0 = sem truncamento. Para LM Studio / llama.cpp com n_ctx≈4096, use ~2048–4096 e
    # aumente n_ctx no servidor se precisar de mais contexto.
    llm_max_user_prompt_chars: int = 0
    # Layout do prompt: índice único de queries + métricas sem repetir PromQL em cada bloco.
    llm_prompt_compact_queries: bool = True
    llm_max_log_lines_per_category: int = 8
    llm_max_log_line_chars: int = 220
    # CSV de chaves de label incluídas primeiro em «Labels (prioridade SRE)»; vazio = default interno.
    llm_label_keys_allowlist: str = (
        "alertname,severity,namespace,service_name,deployment_environment,"
        "environment,env,stage,job,service,app,app_name,pod,instance,container"
    )
    # 0 = sem limite explícito na API (comportamento do provider).
    llm_max_output_tokens: int = 0

    # RabbitMQ (publicação de análises / resolved)
    rabbitmq_enabled: bool = True
    rabbitmq_url: str = "amqp://guest:guest@rabbitmq:5672/"
    rabbitmq_exchange: str = "weather.agent"
    rabbitmq_dlx_exchange: str = "weather.agent.dlx"
    rabbitmq_analysis_queue: str = "weather.agent.analysis"
    rabbitmq_analysis_routing_key: str = "analysis"
    rabbitmq_analysis_dlq: str = "weather.agent.analysis.dlq"
    rabbitmq_resolved_queue: str = "weather.agent.resolved"
    rabbitmq_resolved_routing_key: str = "resolved"
    rabbitmq_resolved_dlq: str = "weather.agent.resolved.dlq"
    rabbitmq_publish_timeout_seconds: float = 5.0

    # Blob Storage (ex.: Azurite: http://127.0.0.1:10000/devstoreaccount1 ou connection string)
    debug_llm_result: bool = False
    blob_storage: str = ""

    # janela de tempo padrão para queries (segundos)
    metrics_lookback: int = 900              # 15 minutos
    logs_lookback: str = "15m"

    @model_validator(mode="after")
    def localize_host_docker_internal_when_unusable(self):
        """Kind/Docker usa host.docker.internal; uvicorn direto no host costuma falhar no DNS."""
        self.grafana_url = _rewrite_host_docker_internal_if_dns_fails(self.grafana_url)
        self.llm_base_url = _rewrite_host_docker_internal_if_dns_fails(self.llm_base_url)
        self.rabbitmq_url = _rewrite_host_docker_internal_if_dns_fails(self.rabbitmq_url)
        blob = (self.blob_storage or "").strip()
        if blob and not blob.startswith("DefaultEndpointsProtocol="):
            self.blob_storage = _rewrite_host_docker_internal_if_dns_fails(blob)
        return self


settings = Settings()
