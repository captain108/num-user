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

# Render ke liye 28s safe limit
REQUEST_TIMEOUT = 28 

# ================= CLIENT & LOCK =================
client = TelegramClient(StringSession(STRING_SESSION), API_ID, API_HASH)
engine_lock = asyncio.Lock()

# ================= CORE ENGINE =================
async def get_json_from_bot(number: str, command: str):
    async with engine_lock: 
        logger.info(f"🚀 MISSION START: Searching {number}")
        
        if not client.is_connected():
            await client.connect()

        try:
            # 1. SEND COMMAND
            await client.send_message(GROUP_ID, f".\n{command} {number}")
            
            bot_msg_future = asyncio.get_event_loop().create_future()

            # 2. BOT MESSAGE LISTENER
            async def handler_msg(event):
                if event.chat_id == GROUP_ID and number in event.message.raw_text:
                    if not bot_msg_future.done():
                        bot_msg_future.set_result(event.message)

            client.add_event_handler(handler_msg, events.NewMessage)

            try:
                bot_msg = await asyncio.wait_for(bot_msg_future, timeout=REQUEST_TIMEOUT)
                logger.info("✅ Bot Response Captured!")
            except asyncio.TimeoutError:
                return {"status": "failed", "msg": "Bot response timeout"}
            finally:
                client.remove_event_handler(handler_msg)

            # 3. FIND BUTTON INDEX (Row/Col logic)
            row_idx, col_idx = None, None
            if bot_msg.reply_markup:
                for r, row in enumerate(bot_msg.reply_markup.rows):
                    for c, btn in enumerate(row.buttons):
                        if "json" in btn.text.lower():
                            row_idx, col_idx = r, c
                            break
            
            if row_idx is None:
                return {"status": "failed", "msg": "Download JSON Button not found"}

            # 4. DOWNLOAD LISTENER (Active BEFORE Click)
            file_future = asyncio.get_event_loop().create_future()

            async def handler_file(event):
                if event.chat_id == GROUP_ID and event.document:
                    if event.document.mime_type == "application/json":
                        if not file_future.done():
                            file_future.set_result(event)

            client.add_event_handler(handler_file, events.NewMessage)

            try:
                # Papaji, click karne se pehle 1.5 second ka gap (Safety)
                await asyncio.sleep(1.5)
                
                # Precise Index-based Click
                await bot_msg.click(row_idx, col_idx)
                logger.info(f"🔘 Clicked Button at Row {row_idx}, Col {col_idx}")
                
                # Wait for file
                file_event = await asyncio.wait_for(file_future, timeout=REQUEST_TIMEOUT)
                logger.info("📎 JSON File Received!")
                
                content = await client.download_media(file_event.message, bytes)
                raw_data = json.loads(content.decode())
                
                return {"status": "success", "data": raw_data}
                
            except asyncio.TimeoutError:
                return {"status": "failed", "msg": "Bot did not send file after click"}
            finally:
                client.remove_event_handler(handler_file)

        except Exception as e:
            logger.error(f"❌ Critical Error: {str(e)}")
            return {"status": "failed", "msg": str(e)}

# ================= WEB APP =================
app = Quart(__name__)

@app.before_serving
async def startup():
    await client.start()
    logger.info("🚀 PAPAJI BRIDGE V6.0 ONLINE")

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
        return jsonify({"status": "failed", "msg": "Internal Error"}), 500
    
    return jsonify(result)

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
