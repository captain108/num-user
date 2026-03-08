import re
import json
import asyncio
import random
import time
from app.config import MIN_DELAY, MAX_DELAY

last_request_time = 0


def extract_json(text):

    match = re.search(r"\{.*\}", text, re.S)

    if not match:
        return None

    try:
        return json.loads(match.group())
    except:
        return None


def clean_data(data, username):

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
