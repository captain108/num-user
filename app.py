import os
import asyncio
import time
import json
import logging
import uuid
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

REQUEST_TIMEOUT = 45 # Thoda extra time for slow bots
CACHE_TTL = 120      # 2 Minutes cache

# ================= CLIENT =================
client = TelegramClient(StringSession(STRING_SESSION), API_ID, API_HASH)
cache = {}

# ================= CLEAN JSON =================
def clean_json(data):
    remove_keys = ["cached", "proxyUsed", "attempt", "cached_at", "credits", "execution_time"]
    if not isinstance(data, dict): return data
    cleaned = {}
    for k, v in data.items():
        if k in remove_keys: continue
        if isinstance(v, dict): cleaned[k] = clean_json(v)
        elif isinstance(v, list): cleaned[k] = [clean_json(x) for x in v]
        else: cleaned[k] = v
    return cleaned

# ================= CORE ENGINE (THE PAPAJI LOGIC) =================
async def get_json_from_bot(number: str, command: str):
    cache_key = f"{command}:{number}"
    
    if cache_key in cache and (time.time() - cache[cache_key]["time"] < CACHE_TTL):
        logger.info(f"⚡ Cache Hit: {cache_key}")
        return cache[cache_key]["data"]

    cmd_text = f"{command} {number}"
    logger.info(f"📤 Sending Command: {cmd_text}")

    try:
        # 1. SEND MESSAGE & GET ID
        sent_msg = await client.send_message(GROUP_ID, cmd_text)
        sent_msg_id = sent_msg.id
        
        # 2. CAPTURE REPLY MESSAGE (The Bot Response)
        reply_msg_future = asyncio.get_event_loop().create_future()

        async def handler_msg(event):
            # Only listen to replies of OUR specific message
            if event.chat_id == GROUP_ID and event.reply_to_msg_id == sent_msg_id:
                if not reply_msg_future.done():
                    reply_msg_future.set_result(event.message)

        client.add_event_handler(handler_msg, events.NewMessage)

        try:
            bot_msg = await asyncio.wait_for(reply_msg_future, timeout=REQUEST_TIMEOUT)
        finally:
            client.remove_event_handler(handler_msg)

        # 3. FIND JSON BUTTON & CLICK
        target_button = None
        if bot_msg.reply_markup:
            for row in bot_msg.reply_markup.rows:
                for btn in row.buttons:
                    if "json" in btn.text.lower():
                        target_button = btn
                        break
            
        if not target_button:
            return {"error": "JSON Button not found in bot response"}

        # 4. CAPTURE FILE (The JSON Document)
        file_future = asyncio.get_event_loop().create_future()

        async def handler_file(event):
            # Bot typically sends the file as a new message, often replying to its own previous message
            # Or just sent in the same group. We filter by document type.
            if event.chat_id == GROUP_ID and event.document:
                if event.document.mime_type == "application/json":
                    # Check if it was sent after our click (time filter)
                    if not file_future.done():
                        file_future.set_result(event)

        client.add_event_handler(handler_file, events.NewMessage)

        try:
            await bot_msg.click(text=target_button.text)
            logger.info("🔘 Clicked JSON Button")
            
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
    logger.info("🚀 PAPAJI BRIDGE ENGINE ONLINE")

@app.route("/api")
async def api_router():
    key = request.args.get("key")
    num = request.args.get("num")
    method = request.args.get("method") # 'num' or 'tg'

    if key != API_KEY: return jsonify({"error": "Unauthorized"}), 401
    if not num or not method: return jsonify({"error": "Missing params"}), 400

    cmd = "/num" if method == "num" else "/tgid"
    start_time = time.time()
    
    data = await get_json_from_bot(num, cmd)
    
    if not data: return jsonify({"status": "failed", "msg": "Timeout or Bot Error"}), 504
    
    return jsonify({
        "status": "success",
        "query": num,
        "method": method,
        "data": data,
        "elapsed": f"{round(time.time() - start_time, 2)}s"
    })

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
