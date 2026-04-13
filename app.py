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
NX_BOT = os.getenv("NX_BOT_USERNAME").replace("@", "")
UNKNOWN_BOT = os.getenv("UNKNOWN_BOT_USERNAME").replace("@", "")

# Render free tier safe limit
REQUEST_TIMEOUT = 28 

# ================= CLIENT & LOCK =================
client = TelegramClient(StringSession(STRING_SESSION), API_ID, API_HASH)
engine_lock = asyncio.Lock()  # Prevents overlapping requests (Anti-Spam)

# ================= CORE ENGINE (THE SMART SCRAPER) =================
async def get_raw_text_from_group(query: str, command: str, target_bot_username: str):
    async with engine_lock: 
        logger.info(f"🚀 MISSION: {command} {query} | Target Lock: {target_bot_username}")
        
        if not client.is_connected():
            await client.connect()

        try:
            # 1. SEND COMMAND (Papaji's Format: Dot + Newline + Command)
            sent_msg = await client.send_message(GROUP_ID, f".\n{command} {query}")
            
            bot_msg_future = asyncio.get_event_loop().create_future()

            # 2. STRICT SENDER LISTENER (Ignores Wrong Bots)
            async def handler_msg(event):
                if event.chat_id == GROUP_ID:
                    sender = await event.get_sender()
                    
                    # Verify if the sender is exactly the bot we want
                    if sender and sender.username and sender.username.lower() == target_bot_username.lower():
                        text = event.message.raw_text.lower()
                        
                        # Match Logic: Is it a reply to our command? Or does it contain the query?
                        is_reply = event.reply_to_msg_id == sent_msg.id
                        has_query = query.lower() in text
                        
                        if is_reply or has_query:
                            if not bot_msg_future.done():
                                # We capture the EXACT text with formatting
                                bot_msg_future.set_result(event.message.raw_text)

            client.add_event_handler(handler_msg, events.NewMessage)

            try:
                # Wait for the specific bot to drop the data
                raw_text = await asyncio.wait_for(bot_msg_future, timeout=REQUEST_TIMEOUT)
                logger.info(f"✅ Target Eliminated! Data Captured from {target_bot_username}")
                
                return {
                    "status": "success", 
                    "data": {
                        "raw_response": raw_text
                    }
                }
                
            except asyncio.TimeoutError:
                logger.warning(f"⏳ Timeout: {target_bot_username} is sleeping or dead.")
                return {"status": "failed", "msg": f"Timeout: {target_bot_username} did not respond"}
            finally:
                client.remove_event_handler(handler_msg) # Clean up memory

        except Exception as e:
            logger.error(f"❌ System Error: {str(e)}")
            return {"status": "failed", "msg": str(e)}

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
