import os
import asyncio
import time
import re
import logging
import random
from collections import defaultdict
from dotenv import load_dotenv
from telethon import TelegramClient, events
from telethon.sessions import StringSession
from quart import Quart, request, jsonify

# ================= LOGGING =================
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger("tg-lookup")

# ================= LOAD ENV =================
load_dotenv()

API_ID = int(os.getenv("API_ID"))
API_HASH = os.getenv("API_HASH")
STRING_SESSION = os.getenv("STRING_SESSION")
GROUP_ID = int(os.getenv("GROUP_ID"))

MIN_DELAY = float(os.getenv("MIN_DELAY", 0.5))
MAX_DELAY = float(os.getenv("MAX_DELAY", 1.5))
REQUEST_TIMEOUT = int(os.getenv("REQUEST_TIMEOUT", 12))
CACHE_TTL = int(os.getenv("CACHE_TTL", 60))
API_KEY = os.getenv("API_KEY", "pak_captain123")

# Command toggles (set to "false" to disable)
SEND_TG = os.getenv("SEND_TG", "true").lower() == "true"
SEND_TGID = os.getenv("SEND_TGID", "true").lower() == "true"

# ================= RATE LIMITING =================
rate_limit_store = defaultdict(list)
RATE_LIMIT = 10
RATE_LIMIT_PERIOD = 60

def is_rate_limited(ip: str) -> bool:
    now = time.time()
    timestamps = rate_limit_store[ip]
    while timestamps and timestamps[0] < now - RATE_LIMIT_PERIOD:
        timestamps.pop(0)
    if len(timestamps) >= RATE_LIMIT:
        return True
    timestamps.append(now)
    return False

# ================= TELEGRAM CLIENT =================
client = TelegramClient(StringSession(STRING_SESSION), API_ID, API_HASH)
pending_requests = {}  # key = phone number, value = asyncio.Future
cache = {}

# ================= RESPONSE VALIDATION =================
INVALID_KEYWORDS = ["unknown command", "command not found", "use /help", "invalid", "error", "failed"]
VALID_HINTS = ["country", "code", "number", "telegram", "id", "phone", "query"]

def is_valid_response(text: str) -> bool:
    text_lower = text.lower()
    if any(word in text_lower for word in INVALID_KEYWORDS):
        return False
    return any(hint in text_lower for hint in VALID_HINTS)

def extract_data(text: str) -> dict:
    result = {}
    query_match = re.search(r"Query:\s*(\+?\d+)", text, re.I)
    if query_match:
        result["query"] = query_match.group(1)
    country_match = re.search(r"Country[:\s]*([A-Za-z\s]+)", text, re.I)
    if country_match:
        result["country"] = country_match.group(1).strip()
    code_match = re.search(r"Country Code[:\s]*(\+\d+)", text, re.I)
    if code_match:
        result["code"] = code_match.group(1)
    number_match = re.search(r"Number[:\s]*(\+?\d+)", text, re.I)
    if number_match:
        result["number"] = number_match.group(1)
    tgid_match = re.search(r"Tg Id[:\s]*(\d+)", text, re.I)
    if tgid_match:
        result["telegram_id"] = tgid_match.group(1)
    return result

def get_cached(value: str):
    entry = cache.get(value)
    if entry and (time.time() - entry["time"]) < CACHE_TTL:
        return entry["result"]
    return None

def set_cache(value: str, result: dict):
    cache[value] = {"result": result, "time": time.time()}

# ================= EVENT HANDLER =================
@client.on(events.NewMessage(chats=GROUP_ID))
async def group_handler(event):
    sender = await event.get_sender()
    if not sender or not sender.bot:
        return
    text = event.raw_text
    logger.info(f"📥 Bot: {text[:200]}")

    query_match = re.search(r"Query:\s*(\+?\d+)", text, re.I)
    if not query_match:
        return
    number = query_match.group(1)

    future = pending_requests.get(number)
    if future and not future.done():
        logger.info(f"✅ Matched response for {number}")
        future.set_result(text)

async def random_delay():
    await asyncio.sleep(random.uniform(MIN_DELAY, MAX_DELAY))

# ================= QUERY BOT (toggleable commands) =================
async def query_bot(value: str, timeout: int = REQUEST_TIMEOUT) -> list:
    future = asyncio.get_event_loop().create_future()
    pending_requests[value] = future
    responses = []

    commands = []
    if SEND_TG:
        commands.append("/tg")
    if SEND_TGID:
        commands.append("/tgid")
    
    if not commands:
        logger.error("Both SEND_TG and SEND_TGID are disabled. No commands to send.")
        return responses

    async def send_command(cmd: str):
        await random_delay()
        command = f"{cmd} {value}"
        logger.info(f"📤 Sending {command}")
        await client.send_message(GROUP_ID, command)

    try:
        # Send each command with a 1 second delay between them
        for idx, cmd in enumerate(commands):
            await send_command(cmd)
            if idx < len(commands) - 1:
                await asyncio.sleep(1.0)

        # Wait for responses (up to number of commands sent)
        for i in range(len(commands)):
            try:
                resp = await asyncio.wait_for(future, timeout=timeout)
                if is_valid_response(resp):
                    responses.append(resp)
                # Create a new future for next response
                future = asyncio.get_event_loop().create_future()
                pending_requests[value] = future
            except asyncio.TimeoutError:
                logger.warning(f"Timeout waiting for response {i+1}/{len(commands)}")
                break
    finally:
        pending_requests.pop(value, None)

    return responses

async def handle_lookup(value: str):
    start_time = time.time()
    cached = get_cached(value)
    if cached:
        return {
            "status": "success",
            "query": value,
            "data": cached,
            "cached": True,
            "response_time_ms": int((time.time() - start_time) * 1000),
        }
    responses = await query_bot(value)
    if not responses:
        return {"status": "error", "message": "No valid bot responses received"}
    merged = {}
    for resp in responses:
        merged.update(extract_data(resp))
    if not merged:
        return {
            "status": "error",
            "message": "Could not extract data",
            "raw_responses": responses,
        }
    set_cache(value, merged)
    return {
        "status": "success",
        "query": value,
        "data": merged,
        "cached": False,
        "response_time_ms": int((time.time() - start_time) * 1000),
    }

# ================= QUART APP =================
app = Quart(__name__)

@app.before_serving
async def startup():
    await client.start()
    logger.info("✅ Telethon client started")
    logger.info(f"Command toggles: SEND_TG={SEND_TG}, SEND_TGID={SEND_TGID}")

@app.after_serving
async def shutdown():
    await client.disconnect()
    logger.info("🛑 Telethon client disconnected")

@app.route("/")
async def home():
    return jsonify({
        "status": "running",
        "client_connected": client.is_connected(),
        "config": {
            "send_tg": SEND_TG,
            "send_tgid": SEND_TGID
        }
    })

@app.route("/api/captainapi")
async def captain_api():
    client_ip = request.remote_addr
    if is_rate_limited(client_ip):
        return jsonify({"status": "error", "message": "Rate limit exceeded"}), 429

    key = request.args.get("key")
    if not key or key != API_KEY:
        return jsonify({"status": "error", "message": "Invalid API key"}), 401

    num = request.args.get("num")
    if not num or not num.strip():
        return jsonify({"status": "error", "message": "Missing 'num'"}), 400
    if not re.match(r"^[A-Za-z0-9+\-\s]+$", num):
        return jsonify({"status": "error", "message": "Invalid characters"}), 400
    if not client.is_connected():
        return jsonify({"status": "error", "message": "Telegram client not ready"}), 503

    result = await handle_lookup(num.strip())
    return jsonify(result)

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
