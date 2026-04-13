import os
import asyncio
import time
import json
import logging
from telethon import TelegramClient, events
from telethon.sessions import StringSession
from quart import Quart, request, jsonify
from dotenv import load_dotenv

# ================= SETUP =================
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("tg-api")

# Environment variables load karein
load_dotenv()

API_ID = int(os.getenv("API_ID"))
API_HASH = os.getenv("API_HASH")
STRING_SESSION = os.getenv("STRING_SESSION")
GROUP_ID = int(os.getenv("GROUP_ID"))
API_KEY = os.getenv("API_KEY")

REQUEST_TIMEOUT = 25 
CACHE_TTL = 120      

# ================= CLIENT =================
client = TelegramClient(StringSession(STRING_SESSION), API_ID, API_HASH)
cache = {}

# ================= CLEAN JSON =================
def clean_json(data):
    remove_keys = ["cached", "proxyUsed", "attempt", "cached_at", "credits"]
    if not isinstance(data, dict): return data
    cleaned = {}
    for k, v in data.items():
        if k in remove_keys: continue
        if isinstance(v, dict): cleaned[k] = clean_json(v)
        elif isinstance(v, list): cleaned[k] = [clean_json(x) for x in v]
        else: cleaned[k] = v
    return cleaned

# ================= CORE ENGINE =================
async def get_json_from_bot(number: str, command: str):
    cache_key = f"{command}:{number}"
    if cache_key in cache and (time.time() - cache[cache_key]["time"] < CACHE_TTL):
        return cache[cache_key]["data"]

    try:
        await client.send_message(GROUP_ID, f"{command} {number}")
        bot_msg_future = asyncio.get_event_loop().create_future()

        async def handler_msg(event):
            # Number matching logic for non-reply bots
            if event.chat_id == GROUP_ID and number in event.message.raw_text:
                sender = await event.get_sender()
                if sender and sender.bot:
                    if not bot_msg_future.done():
                        bot_msg_future.set_result(event.message)

        client.add_event_handler(handler_msg, events.NewMessage)
        try:
            bot_msg = await asyncio.wait_for(bot_msg_future, timeout=REQUEST_TIMEOUT)
        finally:
            client.remove_event_handler(handler_msg)

        # Download JSON Button check
        target_button = None
        if bot_msg.reply_markup:
            for row in bot_msg.reply_markup.rows:
                for btn in row.buttons:
                    if "json" in btn.text.lower():
                        target_button = btn
                        break
        
        if not target_button: return {"error": "JSON Button missing"}

        # Capture File
        file_future = asyncio.get_event_loop().create_future()
        async def handler_file(event):
            if event.chat_id == GROUP_ID and event.document and event.document.mime_type == "application/json":
                if not file_future.done(): file_future.set_result(event)

        client.add_event_handler(handler_file, events.NewMessage)
        try:
            await bot_msg.click(text=target_button.text)
            file_event = await asyncio.wait_for(file_future, timeout=REQUEST_TIMEOUT)
            content = await client.download_media(file_event.message, bytes)
            raw_data = json.loads(content.decode())
            cleaned = clean_json(raw_data)
            cache[cache_key] = {"data": cleaned, "time": time.time()}
            return cleaned
        finally:
            client.remove_event_handler(handler_file)

    except Exception as e:
        logger.error(f"❌ Engine Error: {e}")
        return None

# ================= WEB APP =================
app = Quart(__name__)

@app.before_serving
async def startup():
    await client.start()
    logger.info("🚀 PAPAJI BRIDGE SECURED WITH ENV")

@app.route("/api")
async def api_router():
    if request.args.get("key") != API_KEY: return jsonify({"error": "Unauthorized"}), 401
    
    num = request.args.get("num")
    method = request.args.get("method")
    cmd = "/num" if method == "num" else "/tgid"
    
    data = await get_json_from_bot(num, cmd)
    if not data: return jsonify({"status": "failed", "msg": "Timeout"}), 504
    
    return jsonify({"status": "success", "data": data})

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
