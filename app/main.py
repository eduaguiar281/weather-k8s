from fastapi import FastAPI, Query, HTTPException
from typing import Optional
from datetime import date
import psycopg2
import os
import logging
from pythonjsonlogger import jsonlogger

# ── Logging ────────────────────────────────────────────────
handler = logging.StreamHandler()
handler.setFormatter(jsonlogger.JsonFormatter(
    fmt="%(asctime)s %(name)s %(levelname)s %(message)s",
    datefmt="%Y-%m-%dT%H:%M:%S",
))
logging.basicConfig(level=logging.INFO, handlers=[handler])
logger = logging.getLogger(__name__)

app = FastAPI(
    title="Weather API",
    description="API para consulta de dados climáticos por cidade e data.",
    version="1.0.0",
)


# ── Database ────────────────────────────────────────────────
def get_connection():
    return psycopg2.connect(
        host=os.getenv("DB_HOST", "postgres"),
        port=os.getenv("DB_PORT", "5432"),
        dbname=os.getenv("DB_NAME", "weather-db"),
        user=os.getenv("DB_USER", "postgres"),
        password=os.getenv("DB_PASSWORD", "postgres"),
    )


# ── Endpoints ───────────────────────────────────────────────

@app.get("/hello")
def hello():
    """Retorna uma saudação simples."""
    logger.info("GET /hello called")
    return {"message": "hello world!"}


@app.get("/weather")
def get_weather(
    city: str = Query(..., description="Nome da cidade (máx. 50 caracteres)"),
    date: Optional[str] = Query(None, description="Data no formato YYYY-MM-DD"),
):
    """
    Retorna registros climáticos para uma cidade.
    - Filtra por data se o parâmetro `date` for fornecido.
    - Retorna 400 para entradas inválidas.
    - Retorna 404 se nenhum registro for encontrado.
    """
    logger.info("GET /weather called", extra={"city": city, "date": date})

    # Validação: tamanho da cidade
    if len(city) > 50:
        logger.warning("City name too long", extra={"city": city, "length": len(city)})
        raise HTTPException(
            status_code=400,
            detail="O nome da cidade não pode ter mais de 50 caracteres.",
        )

    # Validação: formato de data
    parsed_date = None
    if date is not None:
        try:
            from datetime import datetime
            parsed_date = datetime.strptime(date, "%Y-%m-%d").date()
        except ValueError:
            logger.warning("Invalid date format", extra={"date": date})
            raise HTTPException(
                status_code=400,
                detail=f"Data inválida: '{date}'. Use o formato YYYY-MM-DD.",
            )

    # Consulta ao banco
    try:
        conn = get_connection()
        cur = conn.cursor()

        if parsed_date:
            cur.execute(
                "SELECT id, city, date, weather FROM weather WHERE city = %s AND date = %s ORDER BY date",
                (city, parsed_date),
            )
        else:
            cur.execute(
                "SELECT id, city, date, weather FROM weather WHERE city = %s ORDER BY date",
                (city,),
            )

        col_names = [desc[0] for desc in cur.description] if cur.description else []
        rows = [dict(zip(col_names, row)) for row in cur.fetchall()]
        cur.close()
        conn.close()

    except Exception as e:
        logger.error(f"Erro ao consultar o banco de dados: {e}", extra={"city": city})
        raise HTTPException(status_code=500, detail="Erro interno ao acessar o banco de dados.")

    # Retorno 404 se não encontrar
    if not rows:
        detail = f"Nenhum registro encontrado para a cidade '{city}'"
        if parsed_date:
            detail += f" na data {parsed_date}."
        logger.warning("No records found", extra={"city": city, "date": str(parsed_date)})
        raise HTTPException(status_code=404, detail=detail)

    logger.info("Weather records returned", extra={"city": city, "count": len(rows)})

    # Serializa date para string
    results = [
        {
            "id": row["id"],
            "city": row["city"],
            "date": str(row["date"]),
            "weather": row["weather"],
        }
        for row in rows
    ]

    return results
