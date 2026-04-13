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
load_dotenv()

API_ID = int(os.getenv("API_ID"))
API_HASH = os.getenv("API_HASH")
STRING_SESSION = os.getenv("STRING_SESSION")
GROUP_ID = int(os.getenv("GROUP_ID"))
API_KEY = os.getenv("API_KEY")

# Render limits ke liye optimized (Render kills at 30s)
REQUEST_TIMEOUT = 28 

# ================= CLIENT & LOCK =================
client = TelegramClient(StringSession(STRING_SESSION), API_ID, API_HASH)
# Ye lock spam rokega. Ek baar mein ek hi ID search hogi.
engine_lock = asyncio.Lock()

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
    async with engine_lock: # Prevent overlapping requests
        logger.info(f"🚀 MISSION START: {number}")
        
        if not client.is_connected():
            await client.connect()

        try:
            # 1. SEND COMMAND
            await client.send_message(GROUP_ID, f"{command} {number}")
            
            bot_msg_future = asyncio.get_event_loop().create_future()

            # 2. BOT RESPONSE LISTENER
            async def handler_msg(event):
                # Check Group ID + Ensure the number is in the bot's reply text
                if event.chat_id == GROUP_ID and number in event.message.raw_text:
                    sender = await event.get_sender()
                    if sender and sender.bot:
                        if not bot_msg_future.done():
                            bot_msg_future.set_result(event.message)

            client.add_event_handler(handler_msg, events.NewMessage)

            try:
                bot_msg = await asyncio.wait_for(bot_msg_future, timeout=REQUEST_TIMEOUT)
                logger.info("📥 Bot response matched successfully!")
            except asyncio.TimeoutError:
                return {"status": "failed", "msg": "Bot did not respond in time"}
            finally:
                client.remove_event_handler(handler_msg)

            # 3. JSON BUTTON SEARCH
            target_button = None
            if bot_msg.reply_markup:
                for row in bot_msg.reply_markup.rows:
                    for btn in row.buttons:
                        if "json" in btn.text.lower():
                            target_button = btn
                            break
            
            if not target_button:
                return {"status": "failed", "msg": "JSON Button missing in bot response"}

            # 4. DOWNLOAD LISTENER & BUTTON CLICK
            file_future = asyncio.get_event_loop().create_future()

            async def handler_file(event):
                if event.chat_id == GROUP_ID and event.document:
                    if event.document.mime_type == "application/json":
                        if not file_future.done():
                            file_future.set_result(event)

            client.add_event_handler(handler_file, events.NewMessage)

            try:
                await bot_msg.click(text=target_button.text)
                logger.info("🔘 Clicked Download JSON")
                
                file_event = await asyncio.wait_for(file_future, timeout=REQUEST_TIMEOUT)
                content = await client.download_media(file_event.message, bytes)
                raw_data = json.loads(content.decode())
                
                cleaned_data = clean_json(raw_data)
                return {"status": "success", "data": cleaned_data}
                
            except asyncio.TimeoutError:
                return {"status": "failed", "msg": "File download timeout"}
            finally:
                client.remove_event_handler(handler_file)

        except Exception as e:
            logger.error(f"❌ Error: {str(e)}")
            return {"status": "failed", "msg": str(e)}

# ================= WEB APP =================
app = Quart(__name__)

@app.before_serving
async def startup():
    await client.start()
    logger.info("🚀 ENGINE LOADED - READY FOR PAPAJI")

@app.route("/api")
async def api_router():
    # Security Key Check
    if request.args.get("key") != API_KEY:
        return jsonify({"status": "failed", "msg": "Invalid Key"}), 401
    
    num = request.args.get("num")
    method = request.args.get("method")
    
    if not num or not method:
        return jsonify({"status": "failed", "msg": "Missing 'num' or 'method' params"}), 400

    cmd = "/num" if method == "num" else "/tgid"
    result = await get_json_from_bot(num, cmd)
    
    if not result:
        return jsonify({"status": "failed", "msg": "Internal System Error"}), 500
    
    return jsonify(result)

if __name__ == "__main__":
    # Render assigns dynamic PORT
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
