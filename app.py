import os
import asyncio
import time
import re
import random
import threading
from dotenv import load_dotenv
from telethon import TelegramClient, events
from telethon.sessions import StringSession
from flask import Flask, request, jsonify

# ================= LOAD ENV =================
load_dotenv()

API_ID = int(os.getenv("API_ID"))
API_HASH = os.getenv("API_HASH")
STRING_SESSION = os.getenv("STRING_SESSION")

GROUP_ID = int(os.getenv("GROUP_ID"))

MIN_DELAY = float(os.getenv("MIN_DELAY", 0.5))
MAX_DELAY = float(os.getenv("MAX_DELAY", 1.5))

# ================= CLIENT =================
client = TelegramClient(StringSession(STRING_SESSION), API_ID, API_HASH)

# ================= CACHE =================
CACHE = {}
CACHE_TTL = 60

CLIENT_READY = False

# ================= FILTER =================
INVALID_KEYWORDS = [
    "unknown command",
    "command not found",
    "use /help",
    "invalid",
    "error",
    "failed"
]

VALID_HINTS = ["country", "code", "number", "telegram"]

def is_valid_response(text):
    text_lower = text.lower()

    for word in INVALID_KEYWORDS:
        if word in text_lower:
            return False

    for hint in VALID_HINTS:
        if hint in text_lower:
            return True

    return False

# ================= CACHE =================
def get_cache(value):
    data = CACHE.get(value)
    if not data:
        return None

    if time.time() - data["time"] > CACHE_TTL:
        CACHE.pop(value, None)
        return None

    return data["result"]

def set_cache(value, result):
    CACHE[value] = {
        "result": result,
        "time": time.time()
    }

# ================= DELAY =================
async def random_delay():
    await asyncio.sleep(random.uniform(MIN_DELAY, MAX_DELAY))

# ================= LISTEN GROUP =================
async def listen_all(value, timeout=6):

    loop = asyncio.get_event_loop()
    future = loop.create_future()
    results = []

    async def handler(event):
        sender = await event.get_sender()

        if sender and sender.bot:
            text = event.raw_text

            print(f"📥 {sender.username} → {text}")

            if str(value) in text:

                if not is_valid_response(text):
                    print("❌ Ignored invalid response")
                    return

                results.append(text)

                if len(results) >= 2:
                    if not future.done():
                        future.set_result(results)

    client.add_event_handler(handler, events.NewMessage(chats=GROUP_ID))

    try:
        await random_delay()

        print(f"📤 Sending /tg {value}")
        await client.send_message(GROUP_ID, f"/tg {value}")

        await asyncio.sleep(0.5)

        print(f"📤 Sending /tgid {value}")
        await client.send_message(GROUP_ID, f"/tgid {value}")

        result = await asyncio.wait_for(future, timeout=timeout)

    except:
        result = results

    client.remove_event_handler(handler)
    return result

# ================= PARSER =================
def extract_data(text):
    return {
        "number": re.search(r"(\d{6,})", text),
        "country": re.search(r"Country[:\s]*([A-Za-z]+)", text),
        "code": re.search(r"(\+\d+)", text)
    }

def clean_extract(data):
    return {k: v.group(1) for k, v in data.items() if v}

def merge_all(texts):
    final = {}

    for t in texts:
        data = clean_extract(extract_data(t))
        for k, v in data.items():
            if k not in final:
                final[k] = v

    return final

# ================= API =================
async def handle_query_api(value):

    start = time.time()

    cached = get_cache(value)
    if cached:
        return {
            "status": "success",
            "query": value,
            "data": cached,
            "cached": True,
            "response_time": f"{int((time.time()-start)*1000)}ms"
        }

    responses = await listen_all(value)

    if not responses:
        return {
            "status": "error",
            "message": "No data found"
        }

    merged = merge_all(responses)
    set_cache(value, merged)

    return {
        "status": "success",
        "query": value,
        "data": merged,
        "cached": False,
        "response_time": f"{int((time.time()-start)*1000)}ms"
    }

# ================= FLASK =================
app = Flask(__name__)

@app.route("/")
def home():
    return jsonify({"status": "running"})

@app.route("/lookup")
def lookup():

    value = request.args.get("id")

    if not value:
        return jsonify({"status": "error", "message": "Missing id"})

    if not CLIENT_READY:
        return jsonify({"status": "error", "message": "System initializing..."})

    future = asyncio.run_coroutine_threadsafe(
        handle_query_api(value),
        MAIN_LOOP
    )

    try:
        result = future.result(timeout=10)
    except:
        return jsonify({"status": "error", "message": "Timeout"})

    return jsonify(result)

# ================= TELETHON START =================
def start_loop(loop):
    asyncio.set_event_loop(loop)
    loop.run_forever()

loop = asyncio.new_event_loop()
MAIN_LOOP = loop

threading.Thread(target=start_loop, args=(loop,), daemon=True).start()

async def init():
    global CLIENT_READY
    await client.start()
    CLIENT_READY = True
    print("✅ Telethon Started")

asyncio.run_coroutine_threadsafe(init(), loop)
