import os
import asyncio
import time
import json
import logging
from collections import defaultdict
from dotenv import load_dotenv
from telethon import TelegramClient, events
from telethon.sessions import StringSession
from quart import Quart, request, jsonify

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("tg-lookup")

load_dotenv()

API_ID = int(os.getenv("API_ID"))
API_HASH = os.getenv("API_HASH")
STRING_SESSION = os.getenv("STRING_SESSION")
GROUP_ID = int(os.getenv("GROUP_ID"))
API_KEY = os.getenv("API_KEY", "pak_captain123")

REQUEST_TIMEOUT = int(os.getenv("REQUEST_TIMEOUT", 30))
CACHE_TTL = int(os.getenv("CACHE_TTL", 60))

# Rate limiting
rate_limit = defaultdict(list)
RATE_LIMIT = 10
RATE_LIMIT_PERIOD = 60

def is_rate_limited(ip: str) -> bool:
    now = time.time()
    times = rate_limit[ip]
    while times and times[0] < now - RATE_LIMIT_PERIOD:
        times.pop(0)
    if len(times) >= RATE_LIMIT:
        return True
    times.append(now)
    return False

client = TelegramClient(StringSession(STRING_SESSION), API_ID, API_HASH)
cache = {}  # {command+number: {"data": dict, "time": float}}

def clean_json(data: dict) -> dict:
    """Remove unwanted fields like cached, proxyUsed, attempt, credits, etc."""
    if not isinstance(data, dict):
        return data
    # Fields to remove (exact or partial)
    remove_keys = ["cached", "proxyUsed", "attempt", "cached_at", "by", "Credits Left", "credits"]
    cleaned = {}
    for k, v in data.items():
        if k in remove_keys:
            continue
        if isinstance(v, dict):
            cleaned[k] = clean_json(v)
        elif isinstance(v, list):
            cleaned[k] = [clean_json(item) for item in v]
        else:
            cleaned[k] = v
    return cleaned

async def get_json_from_bot(number: str, command: str) -> dict:
    """
    Send command (either "/num" or "/tgid"), click Download JSON button,
    download the JSON file, clean it, and return.
    """
    cache_key = f"{command}:{number}"
    entry = cache.get(cache_key)
    if entry and time.time() - entry["time"] < CACHE_TTL:
        logger.info(f"Cache hit for {cache_key}")
        return entry["data"]

    # 1. Send command
    cmd = f"{command} {number}"
    logger.info(f"📤 Sending {cmd}")
    await client.send_message(GROUP_ID, cmd)

    # 2. Wait for the bot's info message (contains the number and buttons)
    try:
        info_msg = await client.wait_for(
            events.NewMessage(chats=GROUP_ID),
            timeout=REQUEST_TIMEOUT,
            condition=lambda e: number in e.raw_text and e.sender_id != (await client.get_me()).id
        )
        msg = info_msg.message
        logger.info(f"📥 Received info message")

        # 3. Find the "Download JSON" button
        if not msg.reply_markup or not msg.reply_markup.rows:
            logger.error("No buttons found")
            return None

        target_button = None
        for row in msg.reply_markup.rows:
            for btn in row.buttons:
                if "JSON" in btn.text:
                    target_button = btn
                    break
            if target_button:
                break

        if not target_button:
            logger.error("No 'Download JSON' button")
            return None

        # 4. Click the button
        logger.info(f"🔘 Clicking button: {target_button.text}")
        await client.click(msg, target_button)

        # 5. Wait for the bot to send the JSON file (document)
        file_msg = await client.wait_for(
            events.NewMessage(chats=GROUP_ID),
            timeout=REQUEST_TIMEOUT,
            condition=lambda e: e.document and e.document.mime_type == "application/json"
        )
        logger.info(f"📎 Received JSON file")

        # 6. Download and parse the file
        file_content = await client.download_media(file_msg.message, bytes)
        raw_data = json.loads(file_content.decode('utf-8'))
        cleaned = clean_json(raw_data)
        cache[cache_key] = {"data": cleaned, "time": time.time()}
        return cleaned

    except asyncio.TimeoutError:
        logger.warning(f"Timeout after {REQUEST_TIMEOUT}s for {command} {number}")
        return None
    except Exception as e:
        logger.error(f"Error: {e}")
        return None

# ================= QUART APP =================
app = Quart(__name__)

@app.before_serving
async def startup():
    await client.start()
    logger.info("✅ Telethon client ready")

@app.after_serving
async def shutdown():
    await client.disconnect()

@app.route("/")
async def home():
    return jsonify({"status": "running", "connected": client.is_connected()})

@app.route("/num")
async def num_endpoint():
    """Send /num command to bot and return cleaned JSON."""
    ip = request.remote_addr
    if is_rate_limited(ip):
        return jsonify({"error": "Rate limit exceeded"}), 429

    key = request.args.get("key")
    if key != API_KEY:
        return jsonify({"error": "Invalid API key"}), 401

    num = request.args.get("num")
    if not num:
        return jsonify({"error": "Missing 'num' parameter"}), 400

    if not client.is_connected():
        return jsonify({"error": "Telegram client not ready"}), 503

    start = time.time()
    data = await get_json_from_bot(num, "/num")
    if not data:
        return jsonify({"status": "error", "message": "No JSON received"}), 404

    return jsonify({
        "status": "success",
        "query": num,
        "command": "num",
        "data": data,
        "response_time_ms": int((time.time() - start) * 1000)
    })

@app.route("/tg")
async def tg_endpoint():
    """Send /tgid command to bot and return cleaned JSON."""
    ip = request.remote_addr
    if is_rate_limited(ip):
        return jsonify({"error": "Rate limit exceeded"}), 429

    key = request.args.get("key")
    if key != API_KEY:
        return jsonify({"error": "Invalid API key"}), 401

    num = request.args.get("num")
    if not num:
        return jsonify({"error": "Missing 'num' parameter"}), 400

    if not client.is_connected():
        return jsonify({"error": "Telegram client not ready"}), 503

    start = time.time()
    data = await get_json_from_bot(num, "/tgid")
    if not data:
        return jsonify({"status": "error", "message": "No JSON received"}), 404

    return jsonify({
        "status": "success",
        "query": num,
        "command": "tgid",
        "data": data,
        "response_time_ms": int((time.time() - start) * 1000)
    })

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
