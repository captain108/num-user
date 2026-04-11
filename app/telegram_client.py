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
        await human_delay()

        try:
            # ✅ use correct command
            await client.send_message(GROUP_ID, f"/tgid {number}")

            # ✅ get last message id (important)
            last_msg = await client.get_messages(GROUP_ID, limit=1)
            last_id = last_msg[0].id if last_msg else 0

            for _ in range(20):

                # ✅ only NEW messages
                msgs = await client.get_messages(GROUP_ID, min_id=last_id, limit=5)

                for msg in msgs:

                    if not msg.text:
                        continue

                    text = msg.text

                    # ✅ OPTIONAL: filter specific bot (RECOMMENDED)
                    # if msg.sender_id != BOT_ID:
                    #     continue

                    # ✅ detect valid response
                    if "Query:" in text and "Result Country" in text:

                        data = extract_json(text)

                        if not data:
                            continue

                        if str(data.get("input")) != str(number):
                            continue

                        print("✅ DATA FOUND:\n", data)

                        return clean_data(data, REPLACE_USERNAME)

                await asyncio.sleep(2)

            return {"error": "No valid response detected"}

        except FloodWaitError as e:

            wait = e.seconds + 5
            print(f"FloodWait {wait}s")

            await asyncio.sleep(wait)

            return await query_number(number)
