import os

API_ID = int(os.getenv("API_ID"))
API_HASH = os.getenv("API_HASH")
STRING_SESSION = os.getenv("STRING_SESSION")

GROUP_ID = int(os.getenv("GROUP_ID"))
API_KEY = os.getenv("API_KEY")

REPLACE_USERNAME = os.getenv("REPLACE_USERNAME", "@captainpapaj1")

MIN_DELAY = int(os.getenv("MIN_DELAY", 6))
MAX_DELAY = int(os.getenv("MAX_DELAY", 10))
