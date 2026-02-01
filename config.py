import os
from dotenv import load_dotenv

load_dotenv()

TOKEN = os.getenv("TOKEN", "")
API_ID = os.getenv("API_ID", "")
API_HASH = os.getenv("API_HASH", "")
CHANNEL_USERNAME = os.getenv("CHANNEL_USERNAME", "")
CHANNEL_URL = os.getenv("CHANNEL_URL", "")

SUPABASE_URL = os.environ.get("SUPBASE_URL", "")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY", "")