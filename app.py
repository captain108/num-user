import os
import asyncio
import json
from fastapi import FastAPI, HTTPException, Request
from telethon import TelegramClient, events

# ================= ENV CONFIG =================

API_ID = int(os.getenv("API_ID"))
API_HASH = os.getenv("API_HASH")
SESSION = os.getenv("SESSION", "session")

GROUP_ID = int(os.getenv("GROUP_ID"))

# comma separated bot ids → "123,456"
ALLOWED_BOTS = list(map(int, os.getenv("ALLOWED_BOTS", "").split(",")))

BOT_TIMEOUT = int(os.getenv("BOT_TIMEOUT", 6))
OWNER_TAG = os.getenv("OWNER_TAG", "@captainpapaj1")

# comma separated keys
API_KEYS = os.getenv("API_KEYS", "").split(",")

# ================= INIT =================

client = TelegramClient(SESSION, API_ID, API_HASH)
app = FastAPI()

pending_future = None

# ================= AUTH =================

def verify_key(request: Request):
    key = request.headers.get("x-api-key")
    if not key or key not in API_KEYS:
        raise HTTPException(status_code=401, detail="Invalid API Key")

# ================= CLEAN =================

def clean_json(data):
    data.pop("credits", None)

    if not data.get("status"):
        return {
            "status": False,
            "error": "Invalid response",
            "owner": OWNER_TAG
        }

    # No data case
    if isinstance(data.get("results"), str):
        if "no data" in data["results"].lower():
            return {
                "status": False,
                "error": "No data found",
                "owner": OWNER_TAG
            }

    # Clean fields
    for r in data.get("results", []):
        if isinstance(r, dict):
            r.pop("id", None)
            r.pop("email", None)

    data["owner"] = OWNER_TAG
    return data

# ================= TELEGRAM LISTENER =================

@client.on(events.NewMessage(chats=GROUP_ID))
async def handler(event):
    global pending_future

    if not pending_future or pending_future.done():
        return

    sender = await event.get_sender()

    if sender.id not in ALLOWED_BOTS:
        return

    text = event.raw_text
    if not text:
        return

    # Fast no data detect
    if "no data found" in text.lower():
        pending_future.set_result({
            "status": False,
            "error": "No data found",
            "owner": OWNER_TAG
        })
        return

    if "{" not in text:
        return

    try:
        data = json.loads(text)
    except:
        return

    cleaned = clean_json(data)

    if not pending_future.done():
        pending_future.set_result(cleaned)

# ================= CORE FUNCTION =================

async def send_and_wait(number):
    global pending_future

    loop = asyncio.get_event_loop()
    pending_future = loop.create_future()

    await client.send_message(GROUP_ID, f"/num {number}")

    try:
        return await asyncio.wait_for(pending_future, timeout=BOT_TIMEOUT)
    except asyncio.TimeoutError:
        return {
            "status": False,
            "error": "Timeout",
            "owner": OWNER_TAG
        }
    finally:
        pending_future = None

# ================= API ROUTE =================

@app.get("/lookup")
async def lookup(number: str, request: Request):

    verify_key(request)

    if not number.isdigit() or len(number) < 8:
        raise HTTPException(status_code=400, detail="Invalid number")

    result = await send_and_wait(number)

    return {
        "status": result.get("status", False),
        "data": result if result.get("status") else None,
        "error": None if result.get("status") else result.get("error"),
        "owner": OWNER_TAG
    }

# ================= START BOTH =================

async def start_all():
    await client.start()
    print("🚀 Userbot started")

    import uvicorn
    config = uvicorn.Config(app, host="0.0.0.0", port=int(os.getenv("PORT", 8000)))
    server = uvicorn.Server(config)

    await server.serve()

if __name__ == "__main__":
    asyncio.run(start_all())
