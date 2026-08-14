import os

SUPABASE_URL = os.getenv("SUPABASE_URL", os.getenv("VITE_SUPABASE_URL", "")).strip()
SUPABASE_ANON_KEY = os.getenv("SUPABASE_ANON_KEY", os.getenv("VITE_SUPABASE_ANON_KEY", "")).strip()

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN", "").strip()
CHANNEL_USERNAME = os.getenv("CHANNEL_USERNAME", "@Athar_Dz_Islamic").strip()
MAGAZINE_FILE = os.getenv("MAGAZINE_FILE", "المشتاقون_إلى_الجنة.pdf").strip()
MAGAZINE_DIR = os.getenv("MAGAZINE_DIR", "magazine.pdf").strip()
PDF_DPI = int(os.getenv("PDF_DPI", "150"))
TIMEZONE = os.getenv("TIMEZONE", "Asia/Riyadh").strip()
PUBLISH_RETRIES = max(1, int(os.getenv("PUBLISH_RETRIES", "3")))
START_PAGE = int(os.getenv("START_PAGE", "9"))
CHANNEL_STAMP = "«رَيْحَانَةُ» المشتاقون إلى الجنة"
