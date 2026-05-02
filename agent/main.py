import logging
import os
from contextlib import asynccontextmanager

from fastapi import BackgroundTasks, FastAPI, Request
from fastapi.responses import JSONResponse
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


@app.get("/health")
async def health():
    return {"status": "ok", "env": ENV}


@app.post("/webhook", status_code=202)
async def receive_alert(request: Request, background_tasks: BackgroundTasks):
    payload = await request.json()
    logger.info(
        "POST /webhook received",
        extra={
            "env": ENV,
            "title": payload.get("title"),
            "status": payload.get("status"),
            "alerts_count": len(payload.get("alerts") or []),
        },
    )

    background_tasks.add_task(agent.handle_and_publish, payload)
    return JSONResponse(
        status_code=202,
        content={"status": "accepted"},
    )
