import os
import asyncio
import json
import time
import uuid
from fastapi import FastAPI, HTTPException, Request
from telethon import TelegramClient, events

# ================= ENV =================

def get_env(name, default=None, required=True):
    val = os.getenv(name, default)
    if required and val is None:
        raise RuntimeError(f"Missing ENV: {name}")
    return val

API_ID = int(get_env("API_ID"))
API_HASH = get_env("API_HASH")
SESSION = get_env("SESSION", "session", required=False)

GROUP_ID = int(get_env("GROUP_ID"))

ALLOWED_BOTS = os.getenv("ALLOWED_BOTS", "")
ALLOWED_BOTS = list(map(int, ALLOWED_BOTS.split(","))) if ALLOWED_BOTS else []

BOT_TIMEOUT = int(get_env("BOT_TIMEOUT", 6, required=False))
OWNER_TAG = get_env("OWNER_TAG", "@captainpapaj1", required=False)

API_KEYS = os.getenv("API_KEYS", "").split(",")

# ================= INIT =================

app = FastAPI()

client = TelegramClient(
    SESSION,
    API_ID,
    API_HASH,
    connection_retries=None
)

# ================= SYSTEM STORAGE =================

request_map = {}      # request_id -> future
number_map = {}       # number -> request_id
cache = {}            # number -> (timestamp, result)

queue = asyncio.Queue()

CACHE_TTL = 300  # 5 minutes

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
        except Exception as e:
            if request_id in request_map:
                request_map[request_id].set_result({
                    "status": False,
                    "error": "Send failed",
                    "owner": OWNER_TAG
                })

        queue.task_done()

# ================= TELEGRAM LISTENER =================

@app.on_event("startup")
async def startup():

    await client.start()
    print("🚀 Userbot started")

    # Start worker
    asyncio.create_task(worker())

    @client.on(events.NewMessage(chats=GROUP_ID))
    async def handler(event):

        sender = await event.get_sender()

        if sender.id not in ALLOWED_BOTS:
            return

        text = event.raw_text or ""

        # detect number (simple match)
        for number, req_id in list(number_map.items()):
            if req_id not in request_map:
                continue

            future = request_map[req_id]

            if future.done():
                continue

            # FAST no data
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

            # Save cache
            cache[number] = (time.time(), result)

            future.set_result(result)

            # cleanup
            request_map.pop(req_id, None)
            number_map.pop(number, None)

# ================= CORE =================

async def process_request(number):

    # ✅ CACHE CHECK
    if number in cache:
        ts, data = cache[number]
        if time.time() - ts < CACHE_TTL:
            return data

    request_id = str(uuid.uuid4())

    loop = asyncio.get_event_loop()
    future = loop.create_future()

    request_map[request_id] = future
    number_map[number] = request_id

    # push to queue
    await queue.put((number, request_id))

    try:
        return await asyncio.wait_for(future, timeout=BOT_TIMEOUT)
    except asyncio.TimeoutError:
        request_map.pop(request_id, None)
        number_map.pop(number, None)
        return {"status": False, "error": "Timeout", "owner": OWNER_TAG}

# ================= ROUTES =================

@app.get("/")
async def home():
    return {"status": True, "message": "API running", "owner": OWNER_TAG}

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
