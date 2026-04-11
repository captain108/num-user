import os
import asyncio
import time
import re
import random
from dotenv import load_dotenv
from telethon import TelegramClient, events
from telethon.sessions import StringSession
from flask import Flask, request, jsonify

# ================= LOAD ENV =================
load_dotenv()

API_ID = int(os.getenv("API_ID"))
API_HASH = os.getenv("API_HASH")
STRING_SESSION = os.getenv("STRING_SESSION")

BOT1 = os.getenv("BOT1")
BOT2 = os.getenv("BOT2")

MIN_DELAY = int(os.getenv("MIN_DELAY", 1))
MAX_DELAY = int(os.getenv("MAX_DELAY", 3))

# ================= CLIENT =================
client = TelegramClient(StringSession(STRING_SESSION), API_ID, API_HASH)

# ================= CACHE =================
CACHE = {}
CACHE_TTL = 60

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

# ================= LISTENER =================
async def listen_bot(bot, command, value, timeout=4):

    loop = asyncio.get_event_loop()
    future = loop.create_future()

    async def handler(event):
        text = event.raw_text

        if str(value) in text:
            if not future.done():
                future.set_result(text)

    client.add_event_handler(handler, events.NewMessage(from_users=bot))

    try:
        await random_delay()
        await client.send_message(bot, f"{command} {value}")
        result = await asyncio.wait_for(future, timeout=timeout)
    except:
        result = None

    client.remove_event_handler(handler)
    return result

# ================= PARALLEL =================
async def fetch_parallel(value):

    task1 = asyncio.create_task(listen_bot(BOT1, "/tgid", value))
    task2 = asyncio.create_task(listen_bot(BOT2, "/tg", value))

    done, pending = await asyncio.wait(
        [task1, task2],
        return_when=asyncio.FIRST_COMPLETED
    )

    results = []

    for d in done:
        if d.result():
            results.append(d.result())

    for p in pending:
        try:
            if p.result():
                results.append(p.result())
        except:
            pass

    return results

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

# ================= API LOGIC =================
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

    responses = await fetch_parallel(value)

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

@app.route("/lookup", methods=["GET"])
def lookup():

    value = request.args.get("id")

    if not value:
        return jsonify({
            "status": "error",
            "message": "Missing id"
        })

    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

    result = loop.run_until_complete(handle_query_api(value))

    return jsonify(result)

# ================= TELETHON START (FIX) =================
def start_background_loop(loop):
    asyncio.set_event_loop(loop)
    loop.run_forever()

loop = asyncio.new_event_loop()
import threading
threading.Thread(target=start_background_loop, args=(loop,), daemon=True).start()

# start telethon client
asyncio.run_coroutine_threadsafe(client.start(), loop)
