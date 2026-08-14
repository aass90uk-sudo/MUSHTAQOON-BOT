import os

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

SUPABASE_URL = os.getenv(
    "SUPABASE_URL",
    os.getenv("VITE_SUPABASE_URL", ""),
).strip()
SUPABASE_ANON_KEY = os.getenv(
    "SUPABASE_ANON_KEY",
    os.getenv("VITE_SUPABASE_ANON_KEY", ""),
).strip()

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN", "").strip()
CHANNEL_USERNAME = os.getenv("CHANNEL_USERNAME", "@Athar_Dz_Islamic").strip()
if CHANNEL_USERNAME.startswith("https://t.me/"):
    CHANNEL_USERNAME = CHANNEL_USERNAME.removeprefix("https://t.me/").strip("/")
if (
    CHANNEL_USERNAME
    and not CHANNEL_USERNAME.startswith("@")
    and not CHANNEL_USERNAME.lstrip("-").isdigit()
):
    CHANNEL_USERNAME = f"@{CHANNEL_USERNAME}"

MAGAZINE_FILE = os.getenv("MAGAZINE_FILE", "المشتاقون_إلى_الجنة.pdf").strip()
MAGAZINE_DIR = os.getenv("MAGAZINE_DIR", "magazine.pdf").strip()
PDF_DPI = int(os.getenv("PDF_DPI", "150"))
TIMEZONE = os.getenv("TIMEZONE", "Asia/Riyadh").strip()
PUBLISH_RETRIES = max(1, int(os.getenv("PUBLISH_RETRIES", "3")))
START_PAGE = int(os.getenv("START_PAGE", "9"))
MAGAZINE_TITLE = os.getenv(
    "MAGAZINE_TITLE",
    "مجلة المشتاقون إلى الجنة",
).strip()
CHANNEL_STAMP = os.getenv(
    "CHANNEL_STAMP",
    "«رَيْحَانَةُ» المشتاقون إلى الجنة",
).strip()

configured_channel_link = os.getenv("CHANNEL_LINK", "").strip()
if configured_channel_link:
    CHANNEL_LINK = configured_channel_link
elif CHANNEL_USERNAME and not CHANNEL_USERNAME.lstrip("-").isdigit():
    CHANNEL_LINK = f"https://t.me/{CHANNEL_USERNAME.lstrip('@')}"
else:
    CHANNEL_LINK = ""
