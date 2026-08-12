import os

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

# ==========================================
# Telegram
# ==========================================

TELEGRAM_TOKEN = os.getenv(
    "TELEGRAM_TOKEN",
    "",
)

CHANNEL_USERNAME = os.getenv(
    "CHANNEL_USERNAME",
    "",
)

# ==========================================
# Groq
# ==========================================

GROQ_API_KEY = os.getenv(
    "GROQ_API_KEY",
    "",
)

GROQ_VISION_MODEL = os.getenv(
    "GROQ_VISION_MODEL",
    "llama-3.2-11b-vision-preview",
)

# ==========================================
# ملف المجلة
# ==========================================

MAGAZINE_FILE = os.getenv(
    "MAGAZINE_FILE",
    "المشتاقون_إلى_الجنة.pdf",
)

MAGAZINE_DIR = os.getenv(
    "MAGAZINE_DIR",
    "magazine_pdf",
)

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
# مكان حفظ تقدم المجلة
# ==========================================

DATA_DIR = os.getenv(
    "DATA_DIR",
    "data",
)

PROGRESS_FILE = os.path.join(
    DATA_DIR,
    "progress.json",
)

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
