"""Ponto de entrada: reexporta a app FastAPI (uvicorn main:app)."""

from alert_agent.presentation.app import app

__all__ = ["app"]
