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
# GROUP_ID ab sirf message bhejne ke kaam aayega
GROUP_ID = int(os.getenv("GROUP_ID")) 
API_KEY = os.getenv("API_KEY")

REQUEST_TIMEOUT = 28 

# ================= CLIENT & LOCK =================
client = TelegramClient(StringSession(STRING_SESSION), API_ID, API_HASH)
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
    async with engine_lock: 
        logger.info(f"🚀 MISSION START: {number}")
        
        if not client.is_connected():
            await client.connect()

        try:
            # 1. SEND COMMAND
            # (Papaji, maine dekha aap . aur new line use kar rahe the, maine waisa hi format de diya)
            await client.send_message(GROUP_ID, f".\n{command} {number}")
            
            bot_msg_future = asyncio.get_event_loop().create_future()

            # 2. GREEDY BOT RESPONSE LISTENER (Bypass Chat ID Match)
            async def handler_msg(event):
                text = str(event.message.message)
                # Agar message mein number hai AUR usme Inline Buttons (reply_markup) hain
                # Toh 100% yehi bot ka reply hai!
                if str(number) in text and event.message.reply_markup:
                    if not bot_msg_future.done():
                        bot_msg_future.set_result(event.message)

            client.add_event_handler(handler_msg, events.NewMessage)

            try:
                bot_msg = await asyncio.wait_for(bot_msg_future, timeout=REQUEST_TIMEOUT)
                logger.info("📥 Greedy Listener Caught the Bot Response!")
            except asyncio.TimeoutError:
                return {"status": "failed", "msg": "Bot did not respond in time"}
            finally:
                client.remove_event_handler(handler_msg)

            # 3. JSON BUTTON SEARCH
            target_button = None
            for row in bot_msg.reply_markup.rows:
                for btn in row.buttons:
                    if "json" in btn.text.lower():
                        target_button = btn
                        break
            
            if not target_button:
                return {"status": "failed", "msg": "JSON Button missing in bot response"}

            # 4. GREEDY DOWNLOAD LISTENER & BUTTON CLICK
            file_future = asyncio.get_event_loop().create_future()

            async def handler_file(event):
                # Jaise hi koi JSON file aaye usko grab karlo
                if event.document and event.document.mime_type == "application/json":
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
    logger.info("🚀 ENGINE LOADED - GREEDY MODE AKTIVE")

@app.route("/api")
async def api_router():
    if request.args.get("key") != API_KEY:
        return jsonify({"status": "failed", "msg": "Invalid Key"}), 401
    
    num = request.args.get("num")
    method = request.args.get("method")
    
    if not num or not method:
        return jsonify({"status": "failed", "msg": "Missing params"}), 400

    cmd = "/num" if method == "num" else "/tgid"
    result = await get_json_from_bot(num, cmd)
    
    if not result:
        return jsonify({"status": "failed", "msg": "Internal System Error"}), 500
    
    return jsonify(result)

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
