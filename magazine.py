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

    # إذا كان المسار الممرر يحتوي على مسار كامل، نستخدمه مباشرة
    if os.path.isabs(magazine_file) and os.path.isfile(magazine_file):
        return magazine_file

    # محاولة العثور على الملف داخل المجلد
    base_dir = MAGAZINE_DIR
    candidates = []

    # 1) المسار المباشر كما هو
    candidates.append(magazine_file)

    # 2) داخل المجلد مع الاسم الأصلي
    candidates.append(os.path.join(base_dir, magazine_file))

    # 3) داخل المجلد مع إضافة .pdf إذا لم يكن موجوداً
    if not magazine_file.lower().endswith(".pdf"):
        candidates.append(os.path.join(base_dir, magazine_file + ".pdf"))

    # 4) البحث داخل المجلد عن أي ملف PDF (يدعم الأسماء العربية المشفرة)
    if os.path.isdir(base_dir):
        for entry in os.listdir(base_dir):
            if entry.lower().endswith(".pdf"):
                candidates.append(os.path.join(base_dir, entry))

    for candidate in candidates:
        if os.path.isfile(candidate):
            return candidate

    # كحل أخير، نعيد المسار المتوقع حتى لو لم يوجد (يظهر خطأ واضح)
    return os.path.join(base_dir, magazine_file)

MAGAZINE_PATH = _resolve_magazine_path()

# ==========================================
# إعداد Bolt Database لحفظ التقدم
# ==========================================

try:
    from Bolt Database import create_client, Client
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
            # لا يوجد صف بعد — نضيفه
            save_progress(next_page=START_PAGE, finished=False)
            return {"next_page": START_PAGE, "finished": False}
        except Exception as e:
            logging.exception(f"[MAGAZINE] فشل قراءة التقدم من Bolt Database: {e}")

    # الاحتياطي: ملف محلي
    import json
    _ensure_local_dir()
    if os.path.isfile(_PROGRESS_FILE):
        try:
            with open(_PROGRESS_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass

    # القيمة الافتراضية
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
    # Bolt Database
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

    # ملف محلي احتياطي
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

        page = document.load_page(page_number - 1)  # 0-indexed
        # مصفوفة التكبير بناءً على DPI
        zoom = PDF_DPI / 72.0
        matrix = fitz.Matrix(zoom, zoom)
        pix = page.get_pixmap(matrix=matrix, alpha=False)
        return pix.tobytes("png")
    finally:
        document.close()

# ==========================================
# استخراج النص من الصورة باستخدام Groq Vision
# ==========================================

# قفل لمنع تداخل عمليات النشر المتزامنة
_publish_lock = asyncio.Lock()

# عميل Groq (يتم إنشاؤه مرة واحدة)
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

# برومبت استخراج النص كما هو موجه في الكود الأصلي
_EXTRACTION_PROMPT = (
    "أنت مساعد متخصص في استخراج النص العربي من الصور بدقة عالية. "
    "قم باستخراج كل النص الموجود في هذه الصفحة كما هو تماماً، "
    "مع الحفاظ على التنسيق والفقرات والأسطر. "
    "لا تضف أي تعليق أو شرح أو مقدمة أو خاتمة. "
    "أعد فقط النص المستخرج كما هو."
)

async def extract_text(image_bytes: bytes) -> str:
    """
    استخراج النص من صورة باستخدام Groq Vision API.
    """
    client = _get_groq_client()
    if client is None:
        raise RuntimeError("عميل Groq غير مهيأ — تحقق من GROQ_API_KEY.")

    # تحويل الصورة إلى base64
    b64 = base64.b64encode(image_bytes).decode("utf-8")
    data_url = f"data:image/png;base64,{b64}"

    def _call_groq() -> str:
        completion = client.chat.completions.create(
            model=GROQ_VISION_MODEL,
            messages=[
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": _EXTRACTION_PROMPT},
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

    # تشغيل الاستدعاء المتزامن في خيط منفصل
    result = await asyncio.to_thread(_call_groq)
    return result.strip()

# ==========================================
# الحد الأقصى لحروف التسمية في تيليجرام
# ==========================================
# تيليجرال يسمح بـ 1024 حرف كحد أقصى للـ caption مع الصورة.
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

    # تنظيف النص المستخرج فقط لمنع تشوه التنسيق
    text = (
        extracted_text
        .strip()
        .replace("\r\n", "\n")
        .replace("\r", "\n")
    )

    # المساحة الصافية المتبقية للنص الحقيقي
    available_length = (
        MAX_CAPTION_LENGTH
        - len(header)
        - len(footer)
        - 2  # الأسطر الفاصلة المضافة عند دمج المكونات
    )

    if available_length < 0:
        raise ValueError("العنوان والختم والرابط يتجاوزون حد 1000 حرف.")

    # إذا كان النص أطول من المساحة المتاحة، نأخذ أكبر قدر ممكن منه
    if len(text) > available_length:
        text_part = text[:available_length]

        # تلافي قطع الكلمة في منتصفها (البحث عن آخر مسافة أو سطر جديد)
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

    # حماية إسعافية نهائية صارمة لضمان السلامة المطلقة في الحالات الاستثنائية دون قطع كلمات
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
            # ==================================
            # تحويل الصفحة إلى صورة
            # ==================================
            image_bytes = await asyncio.to_thread(
                render_page,
                page_number,
            )

            logging.info(f"[MAGAZINE] تم تجهيز صورة الصفحة {page_number}.")

            # ==================================
            # استخراج النص الحقيقي من الصورة
            # ==================================
            logging.info(f"[MAGAZINE] استخراج نص الصفحة {page_number}...")

            extracted_text = await extract_text(image_bytes)

            if not extracted_text:
                raise RuntimeError("Groq لم يعثر على نص في الصفحة.")

            logging.info(f"[MAGAZINE] تم استخراج النص للصفحة {page_number}.")

            # ==================================
            # إنشاء المنشور النهائي
            # ==================================
            final_text = build_text(
                page_number,
                extracted_text,
            )

            # ==================================
            # نشر الصورة + النص في منشور واحد
            # ==================================
            logging.info(f"[MAGAZINE] نشر الصفحة {page_number} مع الصورة والنص...")

            await bot.send_photo(
                chat_id=CHANNEL_USERNAME,
                photo=image_bytes,
                caption=final_text,
            )

            logging.info(f"[MAGAZINE] تم نشر الصفحة {page_number} بنجاح.")

            # ==================================
            # معرفة عدد صفحات المجلة
            # ==================================
            document = fitz.open(MAGAZINE_PATH)
            try:
                total_pages = len(document)
            finally:
                document.close()

            # ==================================
            # حفظ التقدم وثبات العدادات
            # ==================================
            if page_number >= total_pages:
                save_progress(
                    next_page=page_number,  # تثبيت العداد لمنع تجاوز فهرس الصفحات مستقبلاً
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
    
