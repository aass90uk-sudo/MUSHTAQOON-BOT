import asyncio
import base64
import logging
import os
from datetime import datetime, timezone
from typing import Optional

import fitz  # PyMuPDF
from groq import Groq

from config import (
    CHANNEL_USERNAME,
    GROQ_API_KEY,
    GROQ_VISION_MODEL,
    MAGAZINE_DIR,
    MAGAZINE_FILE,
    MAGAZINE_TITLE,
    PDF_DPI,
    START_PAGE,
    SUPABASE_ANON_KEY,
    SUPABASE_URL,
    PUBLISH_RETRIES,
)

# ==========================================
# إعداد مسار ملف المجلة
# ==========================================

def _resolve_magazine_path() -> str:
    """
    بناء مسار ملف المجلة بشكل موثوق.
    يدعم الحالات التالية:
    - MAGAZINE_FILE بدون امتداد .pdf
    - MAGAZINE_FILE مع مجلد مدمج
    - أسماء الملفات العربية المشفرة في GitHub (#U0627...)
    """
    magazine_file = MAGAZINE_FILE

    if os.path.isabs(magazine_file) and os.path.isfile(magazine_file):
        return magazine_file

    base_dir = MAGAZINE_DIR
    candidates = []

    candidates.append(magazine_file)
    candidates.append(os.path.join(base_dir, magazine_file))

    if not magazine_file.lower().endswith(".pdf"):
        candidates.append(os.path.join(base_dir, magazine_file + ".pdf"))

    if os.path.isdir(base_dir):
        for entry in os.listdir(base_dir):
            if entry.lower().endswith(".pdf"):
                candidates.append(os.path.join(base_dir, entry))

    for candidate in candidates:
        if os.path.isfile(candidate):
            return candidate

    return os.path.join(base_dir, magazine_file)

MAGAZINE_PATH = _resolve_magazine_path()

# ==========================================
# إعداد Bolt Database لحفظ التقدم
# ==========================================

try:
    from Bolt_Database import create_client, Client
except ImportError:
    Client = None  # type: ignore
    create_client = None  # type: ignore

_supabase: Optional[Client] = None

def _get_supabase() -> Optional[Client]:
    """تهيئة عميل Bolt Database مرة واحدة."""
    global _supabase
    if _supabase is not None:
        return _supabase
    if create_client is None:
        return None
    if not SUPABASE_URL or not SUPABASE_ANON_KEY:
        logging.warning(
            "[MAGAZINE] SUPABASE_URL أو SUPABASE_ANON_KEY غير موجودين. "
            "سيتم استخدام ملف محلي لحفظ التقدم."
        )
        return None
    try:
        _supabase = create_client(SUPABASE_URL, SUPABASE_ANON_KEY)
        logging.info("[MAGAZINE] تم الاتصال بـ Bolt Database بنجاح.")
    except Exception as e:
        logging.exception(f"[MAGAZINE] فشل الاتصال بـ Bolt Database: {e}")
        _supabase = None
    return _supabase

# ==========================================
# حفظ التقدم في ملف محلي (احتياطي)
# ==========================================

_PROGRESS_FILE = os.path.join(
    os.path.dirname(os.path.abspath(__file__)),
    "data",
    "progress.json",
)

def _ensure_local_dir() -> None:
    """التأكد من وجود مجلد data/ للنسخ الاحتياطي."""
    os.makedirs(os.path.dirname(_PROGRESS_FILE), exist_ok=True)

# ==========================================
# قراءة وحفظ التقدم
# ==========================================

def load_progress() -> dict:
    """
    قراءة حالة التقدم من Bolt Database (أو من ملف محلي احتياطي).
    يعيد dict يحتوي على: next_page, finished
    """
    sb = _get_supabase()
    if sb is not None:
        try:
            result = sb.table("magazine_progress").select("*").eq("id", 1).maybeSingle().execute()
            if result and result.data:
                return {
                    "next_page": result.data["next_page"],
                    "finished": result.data["finished"],
                }
            save_progress(next_page=START_PAGE, finished=False)
            return {"next_page": START_PAGE, "finished": False}
        except Exception as e:
            logging.exception(f"[MAGAZINE] فشل قراءة التقدم من Bolt Database: {e}")

    import json
    _ensure_local_dir()
    if os.path.isfile(_PROGRESS_FILE):
        try:
            with open(_PROGRESS_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass

    default = {"next_page": START_PAGE, "finished": False}
    try:
        with open(_PROGRESS_FILE, "w", encoding="utf-8") as f:
            json.dump(default, f, ensure_ascii=False, indent=2)
    except Exception:
        pass
    return default

def save_progress(next_page: int, finished: bool) -> None:
    """
    حفظ حالة التقدم في Bolt Database (وملف محلي احتياطي).
    """
    updated_at = datetime.now(timezone.utc).isoformat()
    sb = _get_supabase()
    if sb is not None:
        try:
            sb.table("magazine_progress").upsert({
                "id": 1,
                "next_page": next_page,
                "finished": finished,
                "updated_at": updated_at,
            }).execute()
        except Exception as e:
            logging.exception(f"[MAGAZINE] فشل حفظ التقدم في Bolt Database: {e}")

    import json
    _ensure_local_dir()
    try:
        with open(_PROGRESS_FILE, "w", encoding="utf-8") as f:
            json.dump(
                {"next_page": next_page, "finished": finished},
                f,
                ensure_ascii=False,
                indent=2,
            )
    except Exception as e:
        logging.exception(f"[MAGAZINE] فشل حفظ التقدم محلياً: {e}")

# ==========================================
# تحويل صفحة PDF إلى صورة
# ==========================================

def render_page(page_number: int) -> bytes:
    """
    تحويل صفحة PDF (1-indexed) إلى صورة PNG bytes.
    """
    if not os.path.isfile(MAGAZINE_PATH):
        raise FileNotFoundError(
            f"ملف المجلة غير موجود: {MAGAZINE_PATH}. "
            f"تحقق من MAGAZINE_FILE={MAGAZINE_FILE} وMAGAZINE_DIR={MAGAZINE_DIR}."
        )

    document = fitz.open(MAGAZINE_PATH)
    try:
        total = len(document)
        if page_number < 1 or page_number > total:
            raise EOFError(f"الصفحة {page_number} خارج النطاق (1..{total}).")

        page = document.load_page(page_number - 1)
        zoom = PDF_DPI / 72.0
        matrix = fitz.Matrix(zoom, zoom)
        pix = page.get_pixmap(matrix=matrix, alpha=False)
        return pix.tobytes("png")
    finally:
        document.close()

# ==========================================
# برومبت النظام الصارم لاستخراج النص العربي
# ==========================================

SYSTEM_PROMPT = """أنت مستخرج نصوص دقيق ومحترف ومتخصص في اللغة العربية.
مهمتك الأساسية: قراءة الصورة المرسلة إليك لصفحة مجلة "المشتاقون إلى الجنة"
واستخراج النص العربي الموجود داخلها بدقة وأمانة.

⚠️ شروط وقوانين صارمة:
1. اكتب النص المستخرج باللغة العربية الفصحى فقط، كما هو مكتوب في المجلة تماماً.
2. يمنع منعاً باتاً وقاطعاً كتابة أي كلمة أو حرف باللغة الإنجليزية،
   ويحظر تماماً إظهار وسوم التفكير مثل  أو أي تصنيفات مثل Header.
3. يجب ألا يتجاوز طول النص المستخرج الإجمالي عن 1000 حرف كحد أقصى
   لتفادي مشاكل الإرسال مع الصور في تيليجرام.
4. ابدأ بكتابة نص الصفحة مباشرة دون أي مقدمات أو سلام أو عبارات توضيحية إضافية من عندك.
"""

# ==========================================
# استخراج النص من الصورة باستخدام Groq Vision
# ==========================================

_publish_lock = asyncio.Lock()

_groq_client: Optional[Groq] = None

def _get_groq_client() -> Optional[Groq]:
    """تهيئة عميل Groq مرة واحدة."""
    global _groq_client
    if _groq_client is not None:
        return _groq_client
    if not GROQ_API_KEY:
        logging.error("[MAGAZINE] GROQ_API_KEY غير موجود.")
        return None
    try:
        _groq_client = Groq(api_key=GROQ_API_KEY)
        logging.info(f"[MAGAZINE] عميل Groq جاهز. النموذج: {GROQ_VISION_MODEL}")
    except Exception as e:
        logging.exception(f"[MAGAZINE] فشل إنشاء عميل Groq: {e}")
        _groq_client = None
    return _groq_client

async def extract_text(image_bytes: bytes) -> str:
    """
    استخراج النص من صورة باستخدام Groq Vision API.
    """
    client = _get_groq_client()
    if client is None:
        raise RuntimeError("عميل Groq غير مهيأ — تحقق من GROQ_API_KEY.")

    b64 = base64.b64encode(image_bytes).decode("utf-8")
    data_url = f"data:image/png;base64,{b64}"

    def _call_groq() -> str:
        completion = client.chat.completions.create(
            model=GROQ_VISION_MODEL,
            messages=[
                {
                    "role": "system",
                    "content": SYSTEM_PROMPT,
                },
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": "استخرج النص العربي من هذه الصفحة."},
                        {
                            "type": "image_url",
                            "image_url": {"url": data_url},
                        },
                    ],
                }
            ],
            temperature=0.1,
            max_tokens=2000,
        )
        return completion.choices[0].message.content or ""

    result = await asyncio.to_thread(_call_groq)
    return result.strip()

# ==========================================
# الحد الأقصى لحروف التسمية في تيليجرام
# ==========================================
# تيليجرام يسمح بـ 1024 حرف كحد أقصى للـ caption مع الصورة.
# نستخدم 1000 كحد آمن.
MAX_CAPTION_LENGTH = 1000

# ==========================================
# بناء نص المنشور مع تقييد عدد الأحرف
# ==========================================
def build_text(
    page_number: int,
    extracted_text: str,
) -> str:
    """
    بناء نص المنشور وضمان عدم تخطي الحد الأقصى للحروف (1000 حرف).
    يتم اقتطاع النص الحقيقي المستخرج من نهاية آخر كلمة كاملة وتذييله بالخاتمة.
    الختم والرابط جزء من الـ 1000 حرف.
    """
    footer = (
        "بقية تكملة نص الصفحة يوجد في صورة المجلة❤️\n\n"
        f"{CHANNEL_USERNAME}"
    )

    header = (
        f"📖 {MAGAZINE_TITLE}\n"
        f"الصفحة رقم {page_number}\n\n"
    )

    text = (
        extracted_text
        .strip()
        .replace("\r\n", "\n")
        .replace("\r", "\n")
    )

    available_length = (
        MAX_CAPTION_LENGTH
        - len(header)
        - len(footer)
        - 2
    )

    if available_length < 0:
        raise ValueError("العنوان والختم والرابط يتجاوزون حد 1000 حرف.")

    if len(text) > available_length:
        text_part = text[:available_length]

        last_space = max(
            text_part.rfind(" "),
            text_part.rfind("\n"),
        )

        if last_space > 0:
            text_part = text_part[:last_space].rstrip()
    else:
        text_part = text

    final_text = (
        header
        + text_part
        + "\n\n"
        + footer
    )

    if len(final_text) > MAX_CAPTION_LENGTH:
        allowed_text_len = MAX_CAPTION_LENGTH - len(header) - len(footer) - 2
        text_part = text_part[:allowed_text_len]
        last_space = max(text_part.rfind(" "), text_part.rfind("\n"))
        if last_space > 0:
            text_part = text_part[:last_space].rstrip()
        final_text = f"{header}{text_part}\n\n{footer}"

    logging.info(
        f"[MAGAZINE] طول منشور الصفحة {page_number}: {len(final_text)} حرف."
    )

    return final_text

# ==========================================
# نشر الصفحة التالية وإدارة التقدم
# ==========================================
async def publish_next_page(bot) -> bool:
    """
    تقوم بجلب الصفحة الحالية، تحويلها لصورة، استخراج نصها الحقيقي،
    نشرها في التليجرام (صورة + نص)، ثم تحديث حالة التقدم في قاعدة البيانات.
    """
    async with _publish_lock:
        progress = load_progress()

        if progress["finished"]:
            logging.info("[MAGAZINE] انتهت المجلة بالكامل.")
            return True

        page_number = progress["next_page"]
        logging.info(f"[MAGAZINE] بدء تجهيز الصفحة {page_number}...")

        try:
            image_bytes = await asyncio.to_thread(
                render_page,
                page_number,
            )

            logging.info(f"[MAGAZINE] تم تجهيز صورة الصفحة {page_number}.")

            logging.info(f"[MAGAZINE] استخراج نص الصفحة {page_number}...")

            extracted_text = await extract_text(image_bytes)

            if not extracted_text:
                raise RuntimeError("Groq لم يعثر على نص في الصفحة.")

            logging.info(f"[MAGAZINE] تم استخراج النص للصفحة {page_number}.")

            final_text = build_text(
                page_number,
                extracted_text,
            )

            logging.info(f"[MAGAZINE] نشر الصفحة {page_number} مع الصورة والنص...")

            await bot.send_photo(
                chat_id=CHANNEL_USERNAME,
                photo=image_bytes,
                caption=final_text,
            )

            logging.info(f"[MAGAZINE] تم نشر الصفحة {page_number} بنجاح.")

            document = fitz.open(MAGAZINE_PATH)
            try:
                total_pages = len(document)
            finally:
                document.close()

            if page_number >= total_pages:
                save_progress(
                    next_page=page_number,
                    finished=True,
                )
                logging.info("[MAGAZINE] تم نشر آخر صفحة وانتهت المجلة بالكامل.")
            else:
                save_progress(
                    next_page=page_number + 1,
                    finished=False,
                )
                logging.info(f"[MAGAZINE] تم حفظ التقدم. الصفحة القادمة: {page_number + 1}")

            return True

        except EOFError:
            save_progress(
                next_page=page_number,
                finished=True,
            )
            logging.info("[MAGAZINE] لا توجد صفحات أخرى.")
            return True

        except Exception as e:
            logging.exception(f"[MAGAZINE] فشل نشر الصفحة {page_number}: {e}")
            logging.info("[MAGAZINE] فشل النشر؛ ستعيد الجدولة المحاولة تلقائياً.")
            return False
        
