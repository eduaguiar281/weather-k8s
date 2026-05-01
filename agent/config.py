from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    grafana_url: str = "http://grafana:3000"
    grafana_token: str = ""                  # token da service account (glsa_...)

    # configuração da LLM (provider-agnóstico)
    llm_provider: str = "anthropic"          # anthropic | openai
    llm_model: str = "claude-sonnet-4-20250514"
    llm_api_key: str = ""                    # chave da API (anthropic/openai)
    llm_base_url: str = ""                   # base URL customizada (LM Studio, proxies, etc.)

    # janela de tempo padrão para queries (segundos)
    metrics_lookback: int = 900              # 15 minutos
    logs_lookback: str = "15m"

    class Config:
        env_file = ".env"


settings = Settings()
