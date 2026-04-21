import os
import asyncio
import json
import time
import uuid
from fastapi import FastAPI, HTTPException, Request
from telethon import TelegramClient, events

app = FastAPI()

# ================= SAFE ENV =================

def get_env_int(name, default=None):
    try:
        return int(os.getenv(name, default))
    except:
        return default

def get_env_str(name, default=""):
    return os.getenv(name, default)

# Load safely (NO CRASH)
API_ID = get_env_int("API_ID")
API_HASH = get_env_str("API_HASH")
SESSION = get_env_str("SESSION", "session")

GROUP_ID = get_env_int("GROUP_ID")

ALLOWED_BOTS = get_env_str("ALLOWED_BOTS")
ALLOWED_BOTS = list(map(int, ALLOWED_BOTS.split(","))) if ALLOWED_BOTS else []

BOT_TIMEOUT = get_env_int("BOT_TIMEOUT", 6)
OWNER_TAG = get_env_str("OWNER_TAG", "@captainpapaj1")

API_KEYS = get_env_str("API_KEYS").split(",") if get_env_str("API_KEYS") else []

CONFIG_OK = all([API_ID, API_HASH, GROUP_ID])

# ================= INIT =================

client = None
request_map = {}
number_map = {}
cache = {}
queue = asyncio.Queue()
CACHE_TTL = 300

# ================= AUTH =================

def verify_key(request: Request):
    key = request.headers.get("x-api-key")
    if key not in API_KEYS:
        raise HTTPException(status_code=401, detail="Invalid API Key")

# ================= CLEAN =================

def clean_json(data):
    data.pop("credits", None)

    if not data.get("status"):
        return {"status": False, "error": "Invalid response", "owner": OWNER_TAG}

    if isinstance(data.get("results"), str):
        if "no data" in data["results"].lower():
            return {"status": False, "error": "No data found", "owner": OWNER_TAG}

    for r in data.get("results", []):
        if isinstance(r, dict):
            r.pop("id", None)
            r.pop("email", None)

    data["owner"] = OWNER_TAG
    return data

# ================= WORKER =================

async def worker():
    while True:
        number, request_id = await queue.get()

        try:
            await client.send_message(GROUP_ID, f"/num {number}")
        except:
            if request_id in request_map:
                request_map[request_id].set_result({
                    "status": False,
                    "error": "Send failed",
                    "owner": OWNER_TAG
                })

        queue.task_done()

# ================= STARTUP =================

@app.on_event("startup")
async def startup():
    global client

    if not CONFIG_OK:
        print("❌ Missing ENV variables — API running in debug mode")
        return

    client = TelegramClient(SESSION, API_ID, API_HASH)
    await client.start()

    print("🚀 Userbot started")

    asyncio.create_task(worker())

    @client.on(events.NewMessage(chats=GROUP_ID))
    async def handler(event):

        sender = await event.get_sender()
        if sender.id not in ALLOWED_BOTS:
            return

        text = event.raw_text or ""

        for number, req_id in list(number_map.items()):
            if req_id not in request_map:
                continue

            future = request_map[req_id]
            if future.done():
                continue

            if "no data found" in text.lower():
                result = {
                    "status": False,
                    "error": "No data found",
                    "owner": OWNER_TAG
                }
            else:
                if "{" not in text:
                    continue

                try:
                    data = json.loads(text)
                except:
                    continue

                result = clean_json(data)

            cache[number] = (time.time(), result)

            future.set_result(result)

            request_map.pop(req_id, None)
            number_map.pop(number, None)

# ================= CORE =================

async def process_request(number):

    if not CONFIG_OK:
        return {"status": False, "error": "Server not configured"}

    if number in cache:
        ts, data = cache[number]
        if time.time() - ts < CACHE_TTL:
            return data

    request_id = str(uuid.uuid4())
    loop = asyncio.get_event_loop()
    future = loop.create_future()

    request_map[request_id] = future
    number_map[number] = request_id

    await queue.put((number, request_id))

    try:
        return await asyncio.wait_for(future, timeout=BOT_TIMEOUT)
    except asyncio.TimeoutError:
        return {"status": False, "error": "Timeout", "owner": OWNER_TAG}

# ================= ROUTES =================

@app.get("/")
async def home():
    return {
        "status": CONFIG_OK,
        "message": "API Running" if CONFIG_OK else "Missing ENV variables",
        "owner": OWNER_TAG
    }

@app.get("/lookup")
async def lookup(number: str, request: Request):

    verify_key(request)

    if not number.isdigit():
        raise HTTPException(status_code=400, detail="Invalid number")

    result = await process_request(number)

    return {
        "status": result.get("status", False),
        "data": result if result.get("status") else None,
        "error": None if result.get("status") else result.get("error"),
        "owner": OWNER_TAG
    }
