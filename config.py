import os

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

# ==========================================
# Bolt Database (من .env)
# ==========================================
# ملاحظة: متغيرات Bolt Database تأتي من ملف .env تلقائياً
# نحتفظ بنسخة منها هنا للاستخدام في magazine.py

SUPABASE_URL = os.getenv("SUPABASE_URL", os.getenv("VITE_SUPABASE_URL", "")).strip()
SUPABASE_ANON_KEY = os.getenv("SUPABASE_ANON_KEY", os.getenv("VITE_SUPABASE_ANON_KEY", "")).strip()

# ==========================================
# Telegram
# ==========================================

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN", "").strip()

# تم تعيين اسم القناة الافتراضي
CHANNEL_USERNAME = os.getenv("CHANNEL_USERNAME", "@Athar_Dz_Islamic").strip()
if CHANNEL_USERNAME.startswith("https://t.me/"):
    CHANNEL_USERNAME = CHANNEL_USERNAME.removeprefix("https://t.me/").strip("/")
if CHANNEL_USERNAME and not CHANNEL_USERNAME.startswith("@") and not CHANNEL_USERNAME.lstrip("-").isdigit():
    CHANNEL_USERNAME = f"@{CHANNEL_USERNAME}"

# ==========================================
# Groq
# ==========================================

GROQ_API_KEY = os.getenv("GROQ_API_KEY", "").strip()

# تم اعتماد النموذج الحالي للرؤية من Groq (النموذج السابق llama-3.2-11b-vision-preview متوقف)
GROQ_VISION_MODEL = os.getenv(
    "GROQ_VISION_MODEL",
    "qwen/qwen3.6-27b",
).strip()

# ==========================================
# ملف المجلة
# ==========================================

MAGAZINE_FILE = os.getenv("MAGAZINE_FILE", "المشتاقون_إلى_الجنة.pdf").strip()

# تم تعيين اسم المجلد المطابق لقائمة مستودع GitHub
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
# جودة تحويل PDF إلى صورة
# ==========================================

PDF_DPI = int(
    os.getenv(
        "PDF_DPI",
        "150",
    )
)

# ==========================================
# المنطقة الزمنية
# ==========================================

TIMEZONE = os.getenv(
    "TIMEZONE",
    "Asia/Riyadh",
).strip()

# عدد المحاولات الإضافية عند فشل النشر بسبب اتصال مؤقت
PUBLISH_RETRIES = max(1, int(os.getenv("PUBLISH_RETRIES", "3")))

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
