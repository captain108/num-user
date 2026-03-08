import asyncio
from telethon import TelegramClient
from telethon.sessions import StringSession
from telethon.errors import FloodWaitError

from app.config import API_ID, API_HASH, STRING_SESSION, GROUP_ID, REPLACE_USERNAME
from app.utils import extract_json, clean_data, human_delay, rate_limit

client = TelegramClient(StringSession(STRING_SESSION), API_ID, API_HASH)

request_lock = asyncio.Lock()


async def start_client():
    await client.start()
    print("Userbot connected")


async def query_number(number):

    async with request_lock:

        await rate_limit()

        async with client.conversation(GROUP_ID, timeout=120) as conv:

            try:

                await human_delay()

                # send command
                await conv.send_message(f"/num {number}")

                # wait for bot reply
                response = await conv.get_response()

                print("BOT MESSAGE:\n", response.raw_text)

                data = extract_json(response.raw_text)

                if not data:
                    return {"error": "JSON not detected"}

                return clean_data(data, REPLACE_USERNAME)

            except FloodWaitError as e:

                wait = e.seconds + 5

                print(f"FloodWait {wait}s")

                await asyncio.sleep(wait)

                return await query_number(number)
