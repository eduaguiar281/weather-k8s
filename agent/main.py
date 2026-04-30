import logging
from fastapi import FastAPI, Request, HTTPException
from app.agent import AlertAgent

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s"
)
logger = logging.getLogger(__name__)

app = FastAPI(title="Grafana Alert Agent")
agent = AlertAgent()


@app.get("/health")
async def health():
    return {"status": "ok"}


@app.post("/webhook")
async def receive_alert(request: Request):
    payload = await request.json()
    logger.info(f"Alerta recebido: {payload.get('title', 'sem título')}")

    try:
        result = await agent.handle(payload)
        return {"status": "ok", "analysis": result}
    except Exception as e:
        logger.error(f"Erro ao processar alerta: {e}")
        raise HTTPException(status_code=500, detail=str(e))
