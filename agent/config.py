from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    grafana_url: str = "http://grafana:3000"
    grafana_token: str = ""                  # token da service account (glsa_...)
    anthropic_api_key: str = ""

    # janela de tempo padrão para queries (segundos)
    metrics_lookback: int = 900              # 15 minutos
    logs_lookback: str = "15m"

    class Config:
        env_file = ".env"


settings = Settings()
