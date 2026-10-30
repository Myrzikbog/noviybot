import os
from pathlib import Path
from dotenv import load_dotenv

# Load .env file
load_dotenv()

BASE_DIR = Path(__file__).resolve().parent
DB_PATH = BASE_DIR / "game.db"

# Telegram Bot Token
BOT_TOKEN = os.getenv("BOT_TOKEN", "").strip()

# Gemini API Key & Model
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "").strip()
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-2.5-flash").strip()

# Game defaults
MAX_HP = 100
MAX_SANITY = 100
MAX_INVENTORY_CAPACITY = 8

# Validation helper
def validate_config():
    errors = []
    if not BOT_TOKEN:
        errors.append("BOT_TOKEN не установлен в файле .env! Получите его у @BotFather.")
    if not GEMINI_API_KEY:
        errors.append("GEMINI_API_KEY не установлен в файле .env! Получите его на https://aistudio.google.com/app/apikey")
    return errors
