import logging
from contextlib import asynccontextmanager

from fastapi import BackgroundTasks, FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse
from openai import APIConnectionError
from pydantic import BaseModel, Field
from pythonjsonlogger import jsonlogger

from agent import AlertAgent
from config import settings
from llm_blob_storage import ensure_llm_results_storage_sync, list_llm_folder_download_urls

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

ENV = settings.env

agent = AlertAgent()


@asynccontextmanager
async def lifespan(app: FastAPI):
    ensure_llm_results_storage_sync()
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


class LLMResultFile(BaseModel):
    path: str
    download_url: str


class LLMResultFilesResponse(BaseModel):
    files: list[LLMResultFile]


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
    try:
        reply = await agent.chat_test(body.message, body.system)
    except APIConnectionError as e:
        base = settings.llm_base_url or "(API padrão OpenAI — sem LLM_BASE_URL)"
        raise HTTPException(
            status_code=503,
            detail={
                "error": "llm_unreachable",
                "message": (
                    "Sem ligação TCP ao endpoint da LLM (nada a responder nesse host/porta). "
                    "Se usas LM Studio: inicia o modelo, liga o servidor local e confirma a porta. "
                    "No WSL2, se o LM Studio corre no Windows e 127.0.0.1 falha, usa o IP que o "
                    "LM Studio mostra na UI ou o IP do host obtido com: "
                    "grep nameserver /etc/resolv.conf."
                ),
                "llm_base_url": base,
                "exception": str(e),
            },
        ) from e
    return LLMTestResponse(reply=reply)


@app.get("/llm/download-urls", response_model=LLMResultFilesResponse)
async def list_llm_result_download_urls():
    """
    Lista URLs (com SAS de leitura) dos ficheiros na pasta virtual llm_results/
    no Blob Storage. Requer BLOB_STORAGE configurado.
    """
    if not (settings.blob_storage or "").strip():
        raise HTTPException(
            status_code=503,
            detail="BLOB_STORAGE não configurado",
        )
    rows = await list_llm_folder_download_urls()
    files = [LLMResultFile(path=r["path"], download_url=r["download_url"]) for r in rows]
    return LLMResultFilesResponse(files=files)
