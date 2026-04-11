import os
import re
import asyncio
import time
import random
import logging
from collections import defaultdict
from dotenv import load_dotenv
from quart import Quart, request, jsonify
from pyrogram import Client, filters
from pyrogram.types import Message

# ================= LOGGING =================
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger("pyro-lookup")

# ================= LOAD ENV =================
load_dotenv()

API_ID = int(os.getenv("API_ID"))
API_HASH = os.getenv("API_HASH")
PYROGRAM_SESSION_STRING = os.getenv("PYROGRAM_SESSION_STRING")  # Required!
GROUP_ID = int(os.getenv("GROUP_ID"))  # e.g., -1001234567890

MIN_DELAY = float(os.getenv("MIN_DELAY", 0.5))
MAX_DELAY = float(os.getenv("MAX_DELAY", 1.5))
REQUEST_TIMEOUT = int(os.getenv("REQUEST_TIMEOUT", 6))
CACHE_TTL = int(os.getenv("CACHE_TTL", 60))
API_KEY = os.getenv("API_KEY", "pak_captain123")

# ================= RATE LIMITING =================
rate_limit_store = defaultdict(list)
RATE_LIMIT = 10          # requests
RATE_LIMIT_PERIOD = 60   # seconds

def is_rate_limited(ip: str) -> bool:
    now = time.time()
    timestamps = rate_limit_store[ip]
    # Remove old timestamps
    while timestamps and timestamps[0] < now - RATE_LIMIT_PERIOD:
        timestamps.pop(0)
    if len(timestamps) >= RATE_LIMIT:
        return True
    timestamps.append(now)
    return False

# ================= PYROGRAM CLIENT =================
# Using in_memory=True so no session file is written (perfect for Render)
app_client = Client(
    "tg_lookup_bot",
    api_id=API_ID,
    api_hash=API_HASH,
    session_string=PYROGRAM_SESSION_STRING,
    in_memory=True
)

# ================= GLOBAL STATE =================
pending_requests = {}   # {correlation_id: asyncio.Future}
cache = {}              # {value: {"result": merged_data, "time": timestamp}}

# ================= RESPONSE VALIDATION =================
INVALID_KEYWORDS = ["unknown command", "command not found", "use /help", "invalid", "error", "failed"]
VALID_HINTS = ["country", "code", "number", "telegram", "id", "phone"]

def is_valid_response(text: str) -> bool:
    text_lower = text.lower()
    if any(word in text_lower for word in INVALID_KEYWORDS):
        return False
    return any(hint in text_lower for hint in VALID_HINTS)

def extract_data(text: str) -> dict:
    """Extract number, country, and country code from bot response."""
    result = {}
    # Phone number or ID (6+ digits, optional +)
    number_match = re.search(r"(?:phone|id|number)[:\s]*(\+?\d{6,})", text, re.I)
    if not number_match:
        number_match = re.search(r"(\+?\d{7,15})", text)
    if number_match:
        result["number"] = number_match.group(1)
    # Country name
    country_match = re.search(r"country[:\s]*([A-Za-z\s]+)", text, re.I)
    if country_match:
        result["country"] = country_match.group(1).strip()
    # Country code like +55, +1
    code_match = re.search(r"(\+\d{1,4})", text)
    if code_match:
        result["code"] = code_match.group(1)
    return result

def merge_responses(responses: list) -> dict:
    """Merge extracted fields from multiple bot responses."""
    merged = {}
    for resp in responses:
        data = extract_data(resp)
        for k, v in data.items():
            if k not in merged and v:
                merged[k] = v
    return merged

def get_cached(value: str):
    entry = cache.get(value)
    if entry and (time.time() - entry["time"]) < CACHE_TTL:
        return entry["result"]
    return None

def set_cache(value: str, result: dict):
    cache[value] = {"result": result, "time": time.time()}

# ================= EVENT HANDLER =================
@app_client.on_message(filters.chat(GROUP_ID) & filters.bot)
async def group_handler(client: Client, message: Message):
    """Catches bot responses and delivers them to the waiting future."""
    text = message.text or message.caption or ""
    logger.debug(f"📥 {message.from_user.username or message.from_user.id}: {text}")

    # Extract correlation ID from the message (e.g., [REQ:1234567890])
    corr_match = re.search(r"\[REQ:(\d+)\]", text)
    if not corr_match:
        return

    corr_id = corr_match.group(1)
    future = pending_requests.get(corr_id)
    if future and not future.done():
        future.set_result(text)

# ================= SEND COMMANDS AND COLLECT =================
async def random_delay():
    await asyncio.sleep(random.uniform(MIN_DELAY, MAX_DELAY))

async def query_bot(value: str, timeout: int = REQUEST_TIMEOUT) -> list:
    """Send /tg and /tgid commands, collect bot responses."""
    corr_id = str(int(time.time() * 1000)) + str(random.randint(1000, 9999))
    future = asyncio.get_event_loop().create_future()
    pending_requests[corr_id] = future
    responses = []

    async def send_command(command: str):
        await random_delay()
        full_command = f"{command} {value} [REQ:{corr_id}]"
        logger.info(f"📤 Sending {full_command}")
        await app_client.send_message(GROUP_ID, full_command)

    try:
        # Send both commands with a small delay between them
        await send_command("/tg")
        await asyncio.sleep(0.5)
        await send_command("/tgid")

        # Collect up to 2 responses (one per command)
        while len(responses) < 2:
            try:
                resp = await asyncio.wait_for(future, timeout=timeout)
                if is_valid_response(resp):
                    responses.append(resp)
                # Create a new future for the next expected response
                future = asyncio.get_event_loop().create_future()
                pending_requests[corr_id] = future
            except asyncio.TimeoutError:
                break
    finally:
        pending_requests.pop(corr_id, None)

    return responses

# ================= MAIN LOOKUP LOGIC =================
async def handle_lookup(value: str):
    start_time = time.time()

    # 1. Check cache
    cached = get_cached(value)
    if cached:
        return {
            "status": "success",
            "query": value,
            "data": cached,
            "cached": True,
            "response_time_ms": int((time.time() - start_time) * 1000),
        }

    # 2. Query Telegram bot
    responses = await query_bot(value)
    if not responses:
        return {"status": "error", "message": "No valid bot responses received"}

    # 3. Merge extracted data
    merged = merge_responses(responses)
    if not merged:
        return {
            "status": "error",
            "message": "Could not extract data from responses",
            "raw_responses": responses,  # helpful for debugging
        }

    # 4. Cache result
    set_cache(value, merged)
    return {
        "status": "success",
        "query": value,
        "data": merged,
        "cached": False,
        "response_time_ms": int((time.time() - start_time) * 1000),
    }

# ================= QUART APP =================
quart_app = Quart(__name__)

@quart_app.before_serving
async def startup():
    """Starts Pyrogram client when Quart starts."""
    await app_client.start()
    logger.info("✅ Pyrogram client started and listening for updates.")

@quart_app.after_serving
async def shutdown():
    """Stops Pyrogram client when Quart shuts down."""
    await app_client.stop()
    logger.info("🛑 Pyrogram client stopped.")

@quart_app.route("/")
async def home():
    return jsonify({
        "status": "running",
        "client_connected": app_client.is_connected
    })

@quart_app.route("/api/captainapi")
async def captain_api():
    # 1. Rate limiting by IP
    client_ip = request.remote_addr
    if is_rate_limited(client_ip):
        return jsonify({
            "status": "error",
            "message": "Rate limit exceeded. Try again later."
        }), 429

    # 2. API key authentication
    key = request.args.get("key")
    if not key or key != API_KEY:
        return jsonify({"status": "error", "message": "Invalid or missing API key"}), 401

    # 3. Get the number parameter
    num = request.args.get("num")
    if not num or not num.strip():
        return jsonify({"status": "error", "message": "Missing 'num' parameter"}), 400
    if not re.match(r"^[A-Za-z0-9+\-\s]+$", num):
        return jsonify({"status": "error", "message": "Invalid characters in 'num'"}), 400
    if not app_client.is_connected:
        return jsonify({"status": "error", "message": "Telegram client not ready"}), 503

    result = await handle_lookup(num.strip())
    return jsonify(result)

# ================= RUN =================
if __name__ == "__main__":
    quart_app.run(host="0.0.0.0", port=5000)
