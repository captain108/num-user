import os
import asyncio
import time
import json
import uuid
import logging
from collections import defaultdict
from dotenv import load_dotenv
from telethon import TelegramClient, events
from telethon.sessions import StringSession
from quart import Quart, request, jsonify

# ================= SETUP =================
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("tg-api")

load_dotenv()

API_ID = int(os.getenv("API_ID"))
API_HASH = os.getenv("API_HASH")
STRING_SESSION = os.getenv("STRING_SESSION")
GROUP_ID = int(os.getenv("GROUP_ID"))
API_KEY = os.getenv("API_KEY", "pak_captain123")

REQUEST_TIMEOUT = int(os.getenv("REQUEST_TIMEOUT", 30))
CACHE_TTL = int(os.getenv("CACHE_TTL", 60))

# ================= RATE LIMIT =================
rate_limit = defaultdict(list)
RATE_LIMIT = 15
RATE_LIMIT_PERIOD = 60

def is_rate_limited(ip):
    now = time.time()
    times = rate_limit[ip]

    while times and times[0] < now - RATE_LIMIT_PERIOD:
        times.pop(0)

    if len(times) >= RATE_LIMIT:
        return True

    times.append(now)
    return False

# ================= CLIENT =================
client = TelegramClient(StringSession(STRING_SESSION), API_ID, API_HASH)
cache = {}

# ================= CLEAN JSON =================
def clean_json(data):
    remove_keys = ["cached", "proxyUsed", "attempt", "cached_at", "credits"]

    if not isinstance(data, dict):
        return data

    cleaned = {}
    for k, v in data.items():
        if k in remove_keys:
            continue

        if isinstance(v, dict):
            cleaned[k] = clean_json(v)
        elif isinstance(v, list):
            cleaned[k] = [clean_json(x) for x in v]
        else:
            cleaned[k] = v

    return cleaned

# ================= CORE FUNCTION =================
async def get_json_from_bot(number: str, command: str):

    cache_key = f"{command}:{number}"

    if cache_key in cache:
        if time.time() - cache[cache_key]["time"] < CACHE_TTL:
            logger.info(f"⚡ Cache hit {cache_key}")
            return cache[cache_key]["data"]

    cmd = f"{command} {number}"

    logger.info(f"📤 Sending: {cmd}")

    start_time = time.time()
    
    await client.send_message(GROUP_ID, cmd)

    try:
        # STEP 1: WAIT CORRECT MESSAGE (ISOLATED)
        info_msg = await client.wait_for(
            events.NewMessage(chats=GROUP_ID),
            timeout=REQUEST_TIMEOUT,
            condition=lambda e: (
                e.raw_text and
                e.date.timestamp() >= start_time
            )
        )

        msg = info_msg.message
        logger.info("📥 Got response message")

        # STEP 2: FIND JSON BUTTON
        target_button = None
        if msg.reply_markup:
            for row in msg.reply_markup.rows:
                for btn in row.buttons:
                    if "json" in btn.text.lower():
                        target_button = btn
                        break
                if target_button:
                    break

        if not target_button:
            logger.warning("❌ JSON button not found")
            return None

        # STEP 3: CLICK BUTTON
        await msg.click(text=target_button.text)
        logger.info("🔘 Clicked JSON")

        # STEP 4: WAIT JSON FILE
        file_msg = await client.wait_for(
            events.NewMessage(chats=GROUP_ID),
            timeout=REQUEST_TIMEOUT,
            condition=lambda e: (
                e.document and
                e.document.mime_type == "application/json" and
                e.date.timestamp() >= start_time
            )
        )

        logger.info("📎 JSON received")

        # STEP 5: DOWNLOAD + CLEAN
        content = await client.download_media(file_msg.message, bytes)
        raw_data = json.loads(content.decode())

        cleaned = clean_json(raw_data)

        cache[cache_key] = {
            "data": cleaned,
            "time": time.time()
        }

        return cleaned

    except asyncio.TimeoutError:
        logger.warning("⏱ Timeout")
        return None

    except Exception as e:
        logger.error(f"❌ Error: {e}")
        return None

# ================= APP =================
app = Quart(__name__)

@app.before_serving
async def startup():
    await client.start()
    logger.info("✅ Telethon Connected")

@app.route("/")
async def home():
    return jsonify({"status": "running", "connected": client.is_connected()})

# ================= /num =================
@app.route("/num")
async def num_api():

    ip = request.remote_addr

    if is_rate_limited(ip):
        return jsonify({"error": "Rate limit"}), 429

    if request.args.get("key") != API_KEY:
        return jsonify({"error": "Invalid key"}), 401

    number = request.args.get("num")
    if not number:
        return jsonify({"error": "Missing num"}), 400

    start = time.time()

    data = await get_json_from_bot(number, "/num")

    if not data:
        return jsonify({"status": "error", "message": "No data"}), 404

    return jsonify({
        "status": "success",
        "type": "num",
        "query": number,
        "data": data,
        "response_time_ms": int((time.time() - start) * 1000)
    })

# ================= /tg =================
@app.route("/tg")
async def tg_api():

    ip = request.remote_addr

    if is_rate_limited(ip):
        return jsonify({"error": "Rate limit"}), 429

    if request.args.get("key") != API_KEY:
        return jsonify({"error": "Invalid key"}), 401

    number = request.args.get("num")
    if not number:
        return jsonify({"error": "Missing num"}), 400

    start = time.time()

    data = await get_json_from_bot(number, "/tgid")

    if not data:
        return jsonify({"status": "error", "message": "No data"}), 404

    return jsonify({
        "status": "success",
        "type": "tgid",
        "query": number,
        "data": data,
        "response_time_ms": int((time.time() - start) * 1000)
    })

# ================= RUN =================
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
