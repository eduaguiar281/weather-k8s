import logging
import os
from contextlib import asynccontextmanager

from fastapi import BackgroundTasks, FastAPI, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from pythonjsonlogger import jsonlogger

from agent import AlertAgent

# ── Logging (JSON, alinhado ao serviço app) ─────────────────
_handler = logging.StreamHandler()
_handler.setFormatter(
    jsonlogger.JsonFormatter(
        fmt="%(asctime)s %(name)s %(levelname)s %(message)s",
        datefmt="%Y-%m-%dT%H:%M:%S",
    )
)
logging.basicConfig(level=logging.INFO, handlers=[_handler])
logger = logging.getLogger(__name__)

ENV = os.getenv("ENV", "prod")

agent = AlertAgent()


@asynccontextmanager
async def lifespan(app: FastAPI):
    await agent.start()
    try:
        yield
    finally:
        await agent.stop()


app = FastAPI(title="Grafana Alert Agent", lifespan=lifespan)


class LLMTestRequest(BaseModel):
    message: str = Field(..., min_length=1, description="Mensagem do usuário para a LLM")
    system: str | None = Field(
        default=None,
        description="Opcional: instruções de sistema (comportamento do assistente)",
    )


class LLMTestResponse(BaseModel):
    reply: str


@app.get("/health")
async def health():
    return {"status": "ok", "env": ENV}


@app.post("/webhook", status_code=202)
async def receive_alert(request: Request, background_tasks: BackgroundTasks):
    payload = await request.json()
    truncated = payload.get("truncatedAlerts", 0)
    logger.info(
        "POST /webhook received",
        extra={
            "env": ENV,
            "receiver": payload.get("receiver"),
            "notify_status": payload.get("status"),
            "external_url": payload.get("externalURL"),
            "group_key": payload.get("groupKey"),
            "version": payload.get("version"),
            "truncated_alerts": truncated if isinstance(truncated, int) else 0,
            "title": payload.get("title"),
            "alerts_count": len(payload.get("alerts") or []) if isinstance(payload.get("alerts"), list) else 1,
        },
    )

    background_tasks.add_task(agent.handle_and_publish, payload)
    return JSONResponse(
        status_code=202,
        content={"status": "accepted"},
    )


@app.post("/llm/test", response_model=LLMTestResponse)
async def llm_test(body: LLMTestRequest):
    """
    Envia uma mensagem à LLM configurada (mesmas credenciais/modelo do agente)
    e devolve a resposta em texto. Útil para validar integração com o provedor.
    """
    logger.info(
        "POST /llm/test",
        extra={"message_chars": len(body.message), "has_system": body.system is not None},
    )
    reply = await agent.chat_test(body.message, body.system)
    return LLMTestResponse(reply=reply)
