import os

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

# ==========================================
# Telegram
# ==========================================

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN", "").strip()

CHANNEL_USERNAME = os.getenv("CHANNEL_USERNAME", "").strip()
if CHANNEL_USERNAME.startswith("https://t.me/"):
    CHANNEL_USERNAME = CHANNEL_USERNAME.removeprefix("https://t.me/").strip("/")
if CHANNEL_USERNAME and not CHANNEL_USERNAME.startswith("@") and not CHANNEL_USERNAME.lstrip("-").isdigit():
    CHANNEL_USERNAME = f"@{CHANNEL_USERNAME}"

# ==========================================
# Groq
# ==========================================

GROQ_API_KEY = os.getenv("GROQ_API_KEY", "").strip()

GROQ_VISION_MODEL = os.getenv(
    "GROQ_VISION_MODEL", 
    "llama-3.2-11b-vision-preview"
).strip()

# ==========================================
# ملف المجلة
# ==========================================

MAGAZINE_FILE = os.getenv("MAGAZINE_FILE", "المشتاقون_إلى_الجنة.pdf").strip()

# المجلد الذي يحتوي على ملف الـ PDF
MAGAZINE_DIR = os.getenv("MAGAZINE_DIR", "magazine.pdf").strip()

# ==========================================
# صفحة بداية النشر
# ==========================================

START_PAGE = int(
    os.getenv(
        "START_PAGE",
        "9",
    )
)

# ==========================================
# مكان حفظ تقدم المجلة (Supabase)
# ==========================================

SUPABASE_URL = os.getenv("SUPABASE_URL", os.getenv("VITE_SUPABASE_URL", "")).strip()
SUPABASE_ANON_KEY = os.getenv("SUPABASE_ANON_KEY", os.getenv("VITE_SUPABASE_ANON_KEY", "")).strip()

# ==========================================
# جودة تحويل PDF إلى صورة
# ==========================================

PDF_DPI = int(
    os.getenv(
        "PDF_DPI",
        "180",
    )
)

# ==========================================
# المنطقة الزمنية
# ==========================================

TIMEZONE = os.getenv(
    "TIMEZONE",
    "Asia/Riyadh",
)

# ==========================================
# عنوان المجلة
# ==========================================

MAGAZINE_TITLE = os.getenv(
    "MAGAZINE_TITLE",
    "مجلة المشتاقون إلى الجنة",
)

# ==========================================
# رابط القناة اختياري
# ==========================================

CHANNEL_LINK = os.getenv(
    "CHANNEL_LINK",
    "",
)

# ==========================================
# Logging
# ==========================================

print(
    f"[CONFIG] Magazine: {MAGAZINE_FILE}"
)

print(
    f"[CONFIG] Start page: {START_PAGE}"
)

print(
    f"[CONFIG] Vision model: {GROQ_VISION_MODEL}"
)

print(
    f"[CONFIG] Timezone: {TIMEZONE}"
)
