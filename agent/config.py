from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")

    grafana_url: str = "http://grafana:3000"
    grafana_token: str = ""                  # token da service account (glsa_...)

    # configuração da LLM (provider-agnóstico)
    llm_provider: str = "anthropic"          # anthropic | openai
    llm_model: str = "claude-sonnet-4-20250514"
    llm_api_key: str = ""                    # chave da API (anthropic/openai)
    llm_base_url: str = ""                   # base URL customizada (LM Studio, proxies, etc.)

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

    # janela de tempo padrão para queries (segundos)
    metrics_lookback: int = 900              # 15 minutos
    logs_lookback: str = "15m"


settings = Settings()
