import os
import asyncio
import time
import re
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

REQUEST_TIMEOUT = int(os.getenv("REQUEST_TIMEOUT", 20))   # 20 seconds for safety
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
pending = {}   # {normalized_number: asyncio.Future}
cache = {}

def normalize_number(num: str) -> str:
    """Remove leading + and spaces, keep only digits."""
    return re.sub(r'\D', '', num)

def extract(text: str) -> dict:
    data = {}
    q = re.search(r"Query:\s*(\+?\d+)", text, re.I)
    if q: data["query"] = q.group(1)
    c = re.search(r"Country[:\s]*([A-Za-z\s]+)", text, re.I)
    if c: data["country"] = c.group(1).strip()
    cc = re.search(r"Country Code[:\s]*(\+\d+)", text, re.I)
    if cc: data["code"] = cc.group(1)
    n = re.search(r"Number[:\s]*(\+?\d+)", text, re.I)
    if n: data["number"] = n.group(1)
    tid = re.search(r"Tg Id[:\s]*(\d+)", text, re.I)
    if tid: data["telegram_id"] = tid.group(1)
    return data

@client.on(events.NewMessage(chats=GROUP_ID))
async def handler(event):
    text = event.raw_text
    sender = await event.get_sender()
    logger.info(f"📥 [From: {sender.username or sender.id}] {text[:200]}")
    
    # Extract any number (digits) from the message
    numbers_in_msg = re.findall(r'\d{7,15}', text)
    for num in numbers_in_msg:
        normalized = normalize_number(num)
        fut = pending.get(normalized)
        if fut and not fut.done():
            logger.info(f"✅ Matched pending request for {normalized}")
            fut.set_result(text)
            return

async def query(number: str) -> dict:
    norm = normalize_number(number)
    # Check cache
    entry = cache.get(norm)
    if entry and time.time() - entry["time"] < CACHE_TTL:
        logger.info(f"Cache hit for {number}")
        return entry["data"]
    
    # Send command
    fut = asyncio.get_event_loop().create_future()
    pending[norm] = fut
    cmd = f"/tgid {number}"
    logger.info(f"📤 {cmd}")
    await client.send_message(GROUP_ID, cmd)
    
    try:
        resp = await asyncio.wait_for(fut, timeout=REQUEST_TIMEOUT)
        data = extract(resp)
        if data:
            cache[norm] = {"data": data, "time": time.time()}
            return data
        else:
            logger.warning("Extraction failed – raw response: " + resp[:200])
            return None
    except asyncio.TimeoutError:
        logger.warning(f"Timeout after {REQUEST_TIMEOUT}s for {number}")
        return None
    finally:
        pending.pop(norm, None)

app = Quart(__name__)

@app.before_serving
async def startup():
    await client.start()
    logger.info("✅ Client ready – listening to group ID: " + str(GROUP_ID))

@app.after_serving
async def shutdown():
    await client.disconnect()

@app.route("/")
async def home():
    return jsonify({"status": "running", "connected": client.is_connected()})

@app.route("/api/captainapi")
async def captain_api():
    ip = request.remote_addr
    if is_rate_limited(ip):
        return jsonify({"error": "Rate limit"}), 429
    key = request.args.get("key")
    if key != API_KEY:
        return jsonify({"error": "Invalid key"}), 401
    num = request.args.get("num")
    if not num:
        return jsonify({"error": "Missing num"}), 400
    if not client.is_connected():
        return jsonify({"error": "Telegram not ready"}), 503

    start = time.time()
    data = await query(num)
    if not data:
        return jsonify({"status": "error", "message": "No response from bot"}), 404
    return jsonify({
        "status": "success",
        "query": num,
        "data": data,
        "cached": (cache.get(normalize_number(num), {}).get("time", 0) > start - CACHE_TTL),
        "response_ms": int((time.time() - start) * 1000)
    })

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
