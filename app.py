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

# Render free tier 30s limit ke liye optimized
REQUEST_TIMEOUT = 25 

# ================= CLIENT =================
client = TelegramClient(StringSession(STRING_SESSION), API_ID, API_HASH)

# ================= CORE ENGINE =================
async def get_json_from_bot(number: str, command: str):
    logger.info(f"📤 Starting lookup for: {number}")

    try:
        # 1. COMMAND SEND KAREIN
        await client.send_message(GROUP_ID, f"{command} {number}")
        
        # 2. RESPONSE PAKADNE KA LOGIC
        # Hum future use karenge taaki jab message mile tabhi aage badhein
        bot_msg_future = asyncio.get_event_loop().create_future()

        async def handler_msg(event):
            # Check if it's the right group and contains our number
            if event.chat_id == GROUP_ID and number in event.message.raw_text:
                # Check if sender is a bot
                sender = await event.get_sender()
                if sender and sender.bot:
                    if not bot_msg_future.done():
                        bot_msg_future.set_result(event.message)

        client.add_event_handler(handler_msg, events.NewMessage)

        try:
            bot_msg = await asyncio.wait_for(bot_msg_future, timeout=REQUEST_TIMEOUT)
            logger.info("📥 Bot response captured successfully!")
        finally:
            client.remove_event_handler(handler_msg)

        # 3. JSON BUTTON DHUNDEIN
        target_button = None
        if bot_msg.reply_markup:
            for row in bot_msg.reply_markup.rows:
                for btn in row.buttons:
                    if "json" in btn.text.lower():
                        target_button = btn
                        break
        
        if not target_button:
            return {"status": "failed", "msg": "JSON Button not found"}

        # 4. BUTTON CLICK & FILE DOWNLOAD
        file_future = asyncio.get_event_loop().create_future()

        async def handler_file(event):
            if event.chat_id == GROUP_ID and event.document:
                if event.document.mime_type == "application/json":
                    if not file_future.done():
                        file_future.set_result(event)

        client.add_event_handler(handler_file, events.NewMessage)

        try:
            await bot_msg.click(text=target_button.text)
            logger.info("🔘 Clicked 'Download JSON' button")
            
            file_event = await asyncio.wait_for(file_future, timeout=REQUEST_TIMEOUT)
            content = await client.download_media(file_event.message, bytes)
            
            # 5. DATA CLEANING & RETURN
            raw_data = json.loads(content.decode())
            return {"status": "success", "data": raw_data}
            
        finally:
            client.remove_event_handler(handler_file)

    except Exception as e:
        logger.error(f"❌ Error: {str(e)}")
        return None

# ================= WEB APP =================
app = Quart(__name__)

@app.before_serving
async def startup():
    await client.start()
    logger.info("🚀 BRIDGE STARTED - PAPAJI MODE AKTIVE")

@app.route("/api")
async def api_router():
    # Security Check
    if request.args.get("key") != API_KEY:
        return jsonify({"status": "failed", "msg": "Invalid Key"}), 401
    
    num = request.args.get("num")
    method = request.args.get("method")
    
    if not num or not method:
        return jsonify({"status": "failed", "msg": "Missing params"}), 400

    cmd = "/num" if method == "num" else "/tgid"
    result = await get_json_from_bot(num, cmd)
    
    if not result:
        return jsonify({"status": "failed", "msg": "Timeout or System Error"}), 504
    
    return jsonify(result)

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
