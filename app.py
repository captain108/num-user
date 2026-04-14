import os
import asyncio
import logging
from telethon import TelegramClient, events
from telethon.sessions import StringSession
from quart import Quart, request, jsonify
from dotenv import load_dotenv

# ================= SETUP =================
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("tg-api")
load_dotenv()

# Environment Variables Load
API_ID = int(os.getenv("API_ID"))
API_HASH = os.getenv("API_HASH")
STRING_SESSION = os.getenv("STRING_SESSION")
GROUP_ID = int(os.getenv("GROUP_ID"))
API_KEY = os.getenv("API_KEY")

# Remove '@' if Papaji accidentally added it in .env
NX_BOT = (os.getenv("NX_BOT_USERNAME") or "").replace("@", "")
UNKNOWN_BOT = (os.getenv("UNKNOWN_BOT_USERNAME") or "").replace("@", "")

# Render free tier safe limit
REQUEST_TIMEOUT = 28 

# ================= CLIENT & LOCK =================
client = TelegramClient(StringSession(STRING_SESSION), API_ID, API_HASH)
engine_lock = asyncio.Lock()  # Prevents overlapping requests (Anti-Spam)

# ================= CORE ENGINE (THE SMART SCRAPER) =================
async def get_raw_text_from_group(query: str, command: str, target_bot_username: str):
    async with engine_lock:

        if not client.is_connected():
            await client.connect()

        bot_msg_future = asyncio.get_event_loop().create_future()

        # ✅ HANDLER
        async def handler_msg(event):
            sender = await event.get_sender()
            text = event.message.raw_text or ""

            logger.info(f"📩 @{getattr(sender,'username','unknown')}: {text}")

            # ✅ ONLY TARGET BOT
            if sender and sender.username:
                if sender.username.lower() != target_bot_username.lower():
                    return

            # ✅ SMART MATCH
            text_lower = text.lower()
            query_lower = str(query).lower()

            match_query = query_lower in text_lower
            match_keywords = any(x in text_lower for x in ["number", "name", "telegram", "id"])

            if text and (match_query or match_keywords):
                if not bot_msg_future.done():
                    bot_msg_future.set_result(text)

        # ✅ ADD HANDLER FIRST
        client.add_event_handler(handler_msg, events.NewMessage(chats=GROUP_ID))

        # ✅ SEND MESSAGE
        await client.send_message(GROUP_ID, f"{command} {query}")

        try:
            raw_text = await asyncio.wait_for(bot_msg_future, timeout=REQUEST_TIMEOUT)

            return {
                "status": "success",
                "data": {"raw_response": raw_text}
            }

        except asyncio.TimeoutError:
            return {"status": "failed", "msg": "Timeout"}

        finally:
            client.remove_event_handler(handler_msg)
            
# ================= WEB APP ROUTER =================
app = Quart(__name__)

@app.before_serving
async def startup():
    await client.start()
    logger.info("🚀 PAPAJI'S ULTIMATE ROUTER V9.0 ONLINE")

@app.route("/api")
async def api_router():
    # Security Gate
    if request.args.get("key") != API_KEY:
        return jsonify({"status": "failed", "msg": "Access Denied: Invalid Key"}), 401
    
    query = request.args.get("query") 
    method = request.args.get("method")
    
    if not query or not method:
        return jsonify({"status": "failed", "msg": "Missing 'query' or 'method' parameters"}), 400

    # THE BRAIN: Target Selection Logic
    if method == "num":
        cmd = "/num"
        target_bot = NX_BOT
    elif method == "tgid":
        cmd = "/tgid"
        target_bot = NX_BOT
    elif method == "tg":
        cmd = "/tg"
        target_bot = UNKNOWN_BOT
    else:
        return jsonify({"status": "failed", "msg": "Invalid method. Use 'num', 'tgid', or 'tg'"}), 400

    # Fire the Engine
    result = await get_raw_text_from_group(query, cmd, target_bot)
    
    if not result:
        return jsonify({"status": "failed", "msg": "Critical Internal Error"}), 500
    
    return jsonify(result)

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    # Uvicorn is recommended for production, but app.run is fine for simple hosting
    app.run(host="0.0.0.0", port=port)
