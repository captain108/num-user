from fastapi import FastAPI, HTTPException
from app.config import API_KEY
from app.telegram_client import start_client, query_number

app = FastAPI(title="CaptainAPI")


@app.on_event("startup")
async def startup():
    await start_client()


@app.get("/")
async def home():
    return {"status": "CaptainAPI running"}


@app.get("/api/captainapi")
async def captain_api(key: str, num: str):

    if key != API_KEY:
        raise HTTPException(status_code=403, detail="Invalid API key")

    try:

        result = await query_number(num)

        return {
            "status": "success",
            "number": num,
            "result": result
        }

    except Exception as e:

        raise HTTPException(status_code=500, detail=str(e))
