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
REQUEST_TIMEOUT = int(os.getenv("REQUEST_TIMEOUT", 20))   # 20 seconds for slow bots
CACHE_TTL = int(os.getenv("CACHE_TTL", 60))               # cache 60 seconds
API_KEY = os.getenv("API_KEY", "pak_captain123")

# Command toggles – only /tgid is useful here
SEND_TG = os.getenv("SEND_TG", "false").lower() == "true"
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
pending_requests = {}   # {phone_number: asyncio.Future}
cache = {}

# ================= RESPONSE VALIDATION & EXTRACTION =================
INVALID_KEYWORDS = ["unknown command", "command not found", "use /help", "invalid", "error", "failed"]
VALID_HINTS = ["country", "code", "number", "telegram", "id", "phone", "query", "details"]

def is_valid_response(text: str) -> bool:
    text_lower = text.lower()
    if any(word in text_lower for word in INVALID_KEYWORDS):
        return False
    return any(hint in text_lower for hint in VALID_HINTS)

def extract_data(text: str) -> dict:
    result = {}
    # Query (the number we asked for)
    q = re.search(r"Query:\s*(\+?\d+)", text, re.I)
    if q:
        result["query"] = q.group(1)
    # Country
    c = re.search(r"Country[:\s]*([A-Za-z\s]+)", text, re.I)
    if c:
        result["country"] = c.group(1).strip()
    # Country code
    cc = re.search(r"Country Code[:\s]*(\+\d+)", text, re.I)
    if cc:
        result["code"] = cc.group(1)
    # Linked number
    n = re.search(r"Number[:\s]*(\+?\d+)", text, re.I)
    if n:
        result["number"] = n.group(1)
    # Telegram ID
    tid = re.search(r"Tg Id[:\s]*(\d+)", text, re.I)
    if tid:
        result["telegram_id"] = tid.group(1)
    return result

def get_cached(value: str):
    entry = cache.get(value)
    if entry and (time.time() - entry["time"]) < CACHE_TTL:
        logger.info(f"✅ Cache hit for {value}")
        return entry["result"]
    return None

def set_cache(value: str, result: dict):
    cache[value] = {"result": result, "time": time.time()}
    logger.info(f"💾 Cached result for {value} (TTL={CACHE_TTL}s)")

# ================= EVENT HANDLER (listens to ALL group messages) =================
@client.on(events.NewMessage(chats=GROUP_ID))
async def group_handler(event):
    text = event.raw_text
    logger.info(f"📥 New message in group: {text[:200]}")
    
    # Extract any phone number (7-15 digits) from the message
    match = re.search(r"(\+?\d{7,15})", text)
    if not match:
        return
    number = match.group(1)
    logger.info(f"🔍 Extracted number: {number}")
    
    future = pending_requests.get(number)
    if future and not future.done():
        logger.info(f"✅ Delivering response for {number}")
        future.set_result(text)
    else:
        logger.debug(f"No pending request for {number}")

async def random_delay():
    await asyncio.sleep(random.uniform(MIN_DELAY, MAX_DELAY))

# ================= SEND COMMAND AND WAIT =================
async def query_bot(value: str, timeout: int = REQUEST_TIMEOUT) -> list:
    """Send only enabled commands and wait for bot responses."""
    commands = []
    if SEND_TGID:
        commands.append("/tgid")
    if SEND_TG:
        commands.append("/tg")
    if not commands:
        logger.error("No commands enabled – check SEND_TG / SEND_TGID env vars")
        return []

    future = asyncio.get_event_loop().create_future()
    pending_requests[value] = future
    responses = []

    async def send_command(cmd: str):
        await random_delay()
        full_cmd = f"{cmd} {value}"
        logger.info(f"📤 Sending {full_cmd}")
        await client.send_message(GROUP_ID, full_cmd)

    try:
        for i, cmd in enumerate(commands):
            await send_command(cmd)
            if i < len(commands) - 1:
                await asyncio.sleep(1.5)   # delay between different commands

        # Wait for a response for each command we sent
        for i in range(len(commands)):
            try:
                resp = await asyncio.wait_for(future, timeout=timeout)
                if is_valid_response(resp):
                    responses.append(resp)
                else:
                    logger.warning(f"Response {i+1} failed validity check")
                # Create a new future for the next expected response
                future = asyncio.get_event_loop().create_future()
                pending_requests[value] = future
            except asyncio.TimeoutError:
                logger.warning(f"Timeout waiting for response {i+1}")
                break
    finally:
        pending_requests.pop(value, None)

    return responses

# ================= MAIN LOOKUP LOGIC =================
async def handle_lookup(value: str):
    start = time.time()
    # 1. Check cache
    cached = get_cached(value)
    if cached:
        return {
            "status": "success",
            "query": value,
            "data": cached,
            "cached": True,
            "response_time_ms": int((time.time() - start) * 1000),
        }
    # 2. Query bot (only if not cached)
    responses = await query_bot(value)
    if not responses:
        return {"status": "error", "message": "No valid bot responses received"}
    # 3. Merge extracted data
    merged = {}
    for resp in responses:
        merged.update(extract_data(resp))
    if not merged:
        return {
            "status": "error",
            "message": "Could not extract data",
            "raw_responses": responses,
        }
    # 4. Store in cache
    set_cache(value, merged)
    return {
        "status": "success",
        "query": value,
        "data": merged,
        "cached": False,
        "response_time_ms": int((time.time() - start) * 1000),
    }

# ================= QUART APP =================
app = Quart(__name__)

@app.before_serving
async def startup():
    await client.start()
    logger.info("✅ Telethon client started")
    logger.info(f"Commands: /tgid={SEND_TGID}, /tg={SEND_TG} | Timeout={REQUEST_TIMEOUT}s | Cache TTL={CACHE_TTL}s")

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
            "send_tgid": SEND_TGID,
            "timeout": REQUEST_TIMEOUT,
            "cache_ttl": CACHE_TTL
        }
    })

@app.route("/api/captainapi")
async def captain_api():
    # Rate limit
    ip = request.remote_addr
    if is_rate_limited(ip):
        return jsonify({"status": "error", "message": "Rate limit exceeded"}), 429
    # Auth
    key = request.args.get("key")
    if not key or key != API_KEY:
        return jsonify({"status": "error", "message": "Invalid API key"}), 401
    # Parameter
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
