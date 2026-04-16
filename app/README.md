# Weather API

API REST construída com **FastAPI** e **uvicorn** para consulta de dados climáticos por cidade e data.

---

## Pré-requisitos

- [Docker](https://www.docker.com/) e [Docker Compose](https://docs.docker.com/compose/) instalados.

---

## Como executar

### 1. Subir toda a stack

Na raiz da pasta `observability/`, execute:

```bash
docker compose up -d
```

O banco de dados PostgreSQL será criado automaticamente com a tabela `weather` e os dados iniciais (5 cidades × 10 dias).

### 2. Verificar se a API está no ar

```bash
curl http://localhost:8000/hello
```

Resposta esperada:
```json
{ "message": "hello world!" }
```

### 3. Documentação interativa

Acesse no navegador:
```
http://localhost:8000/docs
```

---

## Endpoints

### `GET /hello`

Retorna uma saudação simples.

**Resposta:**
```json
{ "message": "hello world!" }
```

---

### `GET /weather`

Retorna registros climáticos para uma cidade. Aceita filtro opcional por data.

**Query parameters:**

| Parâmetro | Tipo   | Obrigatório | Descrição                        |
|-----------|--------|-------------|----------------------------------|
| `city`    | string | Sim         | Nome da cidade (máx. 50 chars)   |
| `date`    | string | Não         | Data no formato `YYYY-MM-DD`     |

**Exemplos:**

```bash
# Todos os registros de São Paulo
curl "http://localhost:8000/weather?city=São Paulo"

# Registro de Rio de Janeiro em uma data específica
curl "http://localhost:8000/weather?city=Rio de Janeiro&date=2024-04-05"
```

**Respostas:**

| Código | Situação                                      |
|--------|-----------------------------------------------|
| 200    | Registros encontrados                         |
| 400    | Cidade > 50 chars ou data em formato inválido |
| 404    | Nenhum registro encontrado                    |
| 500    | Erro interno no banco de dados                |

**Exemplo de resposta 200:**
```json
[
  {
    "id": 1,
    "city": "São Paulo",
    "date": "2024-04-01",
    "weather": "Cloudy with light drizzle"
  }
]
```

---

## Variáveis de ambiente

A aplicação lê as seguintes variáveis (com valores padrão para uso local com Docker Compose):

| Variável      | Padrão       | Descrição               |
|---------------|--------------|-------------------------|
| `DB_HOST`     | `postgres`   | Host do banco de dados  |
| `DB_PORT`     | `5432`       | Porta do PostgreSQL      |
| `DB_NAME`     | `weather-db` | Nome do banco            |
| `DB_USER`     | `postgres`   | Usuário do banco         |
| `DB_PASSWORD` | `postgres`   | Senha do banco           |

---

## Cidades disponíveis nos dados iniciais

- São Paulo
- Rio de Janeiro
- Curitiba
- Manaus
- Fortaleza

Período: `2024-04-01` a `2024-04-10`

---

## Parar a stack

```bash
docker compose down
```

Para remover também os volumes (apaga os dados do banco):

```bash
docker compose down -v
```
