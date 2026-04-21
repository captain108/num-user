import os
import asyncio
import json
import time
import uuid
from fastapi import FastAPI, HTTPException, Request
from telethon import TelegramClient, events
from telethon.sessions import StringSession

# ================= ENV =================

def env(name, default=None):
    return os.getenv(name, default)

API_ID = int(env("API_ID", 0))
API_HASH = env("API_HASH")
STRING_SESSION = env("STRING_SESSION")

GROUP_ID = int(env("GROUP_ID", 0))

# 🔥 SINGLE BOT ONLY
TARGET_BOT_ID = int(env("TARGET_BOT_ID", 0))

BOT_TIMEOUT = int(env("BOT_TIMEOUT", 6))
OWNER_TAG = env("OWNER_TAG", "@captainpapaj1")

API_KEYS = env("API_KEYS", "")
API_KEYS = API_KEYS.split(",") if API_KEYS else []

CACHE_TTL = 300

# ================= INIT =================

app = FastAPI()
client = None

request_map = {}
number_map = {}
cache = {}

queue = asyncio.Queue()

CONFIG_OK = all([API_ID, API_HASH, STRING_SESSION, GROUP_ID, TARGET_BOT_ID])

# ================= AUTH =================

def verify_key(request: Request):
    # try header first
    key = request.headers.get("x-api-key")

    # fallback to query param
    if not key:
        key = request.query_params.get("key")

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
        print("❌ Missing ENV")
        return

    try:
        client = TelegramClient(
            StringSession(STRING_SESSION),
            API_ID,
            API_HASH,
            connection_retries=None
        )

        await client.start()
        print("🚀 Userbot connected")

        asyncio.create_task(worker())

        @client.on(events.NewMessage(chats=GROUP_ID))
        async def handler(event):

            sender = await event.get_sender()

            # 🔥 ONLY TARGET BOT
            if sender.id != TARGET_BOT_ID:
                return

            text = event.raw_text or ""

            for number, req_id in list(number_map.items()):

                if req_id not in request_map:
                    continue

                future = request_map[req_id]

                if future.done():
                    continue

                # fast no data
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

                # cache
                cache[number] = (time.time(), result)

                future.set_result(result)

                # cleanup
                request_map.pop(req_id, None)
                number_map.pop(number, None)

    except Exception as e:
        print("❌ Startup error:", e)

# ================= CORE =================

async def process_request(number):

    # cache
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
        "message": "API Running" if CONFIG_OK else "Missing ENV",
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
