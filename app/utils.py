import re
import json
import asyncio
import random
import time
from app.config import MIN_DELAY, MAX_DELAY

last_request_time = 0


def extract_json(text):

    if not text:
        return None

    # remove markdown formatting
    text = text.replace("```json", "").replace("```", "")

    # find JSON block
    match = re.search(r"\{[\s\S]*\}", text)

    if not match:
        print("JSON not detected in message:")
        print(text)
        return None

    json_text = match.group()

    try:
        return json.loads(json_text)
    except Exception as e:
        print("JSON parse error:", e)
        print("RAW JSON:", json_text)
        return None


def clean_data(data, username):

    if isinstance(data, dict):
        data["requested_by"] = username
        data["developer"] = username

    return data


async def human_delay():

    delay = random.uniform(MIN_DELAY, MAX_DELAY)

    print(f"Sleeping {delay:.2f}s")

    await asyncio.sleep(delay)


async def rate_limit():

    global last_request_time

    now = time.time()

    diff = now - last_request_time

    if diff < MIN_DELAY:
        await asyncio.sleep(MIN_DELAY - diff)

    last_request_time = time.time()
