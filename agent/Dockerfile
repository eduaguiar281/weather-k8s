FROM python:3.12-slim

COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

WORKDIR /app

COPY pyproject.toml .
RUN uv sync --no-dev --no-install-project

COPY . .

ENV PYTHONPATH=/app
ENV PATH="/app/.venv/bin:${PATH}"

EXPOSE 8000

# Usa uvicorn em Linux a partir do .venv criado em `RUN uv sync`.
# `.dockerignore` inclui `.venv/` para o último `COPY . .` não substituir
# esse ambiente pelo .venv macOS do host de desenvolvimento.
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
