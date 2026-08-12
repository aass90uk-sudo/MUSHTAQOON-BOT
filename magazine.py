import os
import base64
import asyncio
import logging
import threading
import glob

import fitz
import requests
from groq import Groq

from config import (
    GROQ_API_KEY,
    GROQ_VISION_MODEL,
    MAGAZINE_FILE,
    MAGAZINE_DIR,
    SUPABASE_URL,
    SUPABASE_ANON_KEY,
    PDF_DPI,
    MAGAZINE_TITLE,
    CHANNEL_USERNAME,
    CHANNEL_LINK,
    START_PAGE,
)


# ==========================================
# منع تشغيل عمليتي نشر في نفس الوقت
# ==========================================

_publish_lock = asyncio.Lock()

_sync_lock = threading.Lock()


# ==========================================
# Groq
# ==========================================

groq_client = (
    Groq(api_key=GROQ_API_KEY)
    if GROQ_API_KEY
    else None
)


# ==========================================
# مسار ملف المجلة
# ==========================================

def resolve_magazine_path() -> str:
    """Resolve the PDF even when Railway supplies a relative/full path."""
    configured_path = os.path.expanduser(MAGAZINE_FILE.strip())
    candidates = [configured_path]

    if not os.path.isabs(configured_path):
        candidates.insert(0, os.path.join(MAGAZINE_DIR, configured_path))

    for candidate in candidates:
        if os.path.isfile(candidate):
            return candidate

    pdf_files = sorted(glob.glob(os.path.join(MAGAZINE_DIR, "*.pdf")))
    if len(pdf_files) == 1:
        logging.warning(
            "[MAGAZINE] MAGAZINE_FILE did not match exactly; using %s",
            pdf_files[0],
        )
        return pdf_files[0]

    return candidates[0]


MAGAZINE_PATH = resolve_magazine_path()


# ==========================================
# قراءة التقدم (من Supabase)
# ==========================================

def load_progress():
    """Read the bot's progress from Supabase. Falls back to START_PAGE on failure."""

    fallback = {
        "next_page": START_PAGE,
        "finished": False,
    }

    if not SUPABASE_URL or not SUPABASE_ANON_KEY:
        logging.warning(
            "[PROGRESS] SUPABASE_URL أو SUPABASE_ANON_KEY غير موجود؛ "
            "استخدام القيمة الافتراضية."
        )
        return fallback

    try:
        response = requests.get(
            f"{SUPABASE_URL}/rest/v1/magazine_progress?id=eq.1",
            headers={
                "apikey": SUPABASE_ANON_KEY,
                "Authorization": f"Bearer {SUPABASE_ANON_KEY}",
            },
            timeout=10,
        )
        response.raise_for_status()
        rows = response.json()

        if not rows:
            logging.info(
                "[PROGRESS] لا يوجد سجل بعد؛ البدء من الصفحة %s.",
                START_PAGE,
            )
            return fallback

        row = rows[0]
        return {
            "next_page": int(row["next_page"]),
            "finished": bool(row["finished"]),
        }

    except Exception as e:
        logging.error(
            "[PROGRESS] خطأ في قراءة التقدم من Supabase: %s", e
        )
        return fallback


# ==========================================
# حفظ التقدم (في Supabase)
# ==========================================

def save_progress(
    next_page: int,
    finished: bool = False,
):
    """Persist the bot's progress to Supabase via upsert."""

    if not SUPABASE_URL or not SUPABASE_ANON_KEY:
        logging.error(
            "[PROGRESS] لا يمكن الحفظ: SUPABASE_URL أو SUPABASE_ANON_KEY غير موجود."
        )
        return

    payload = {
        "id": 1,
        "next_page": next_page,
        "finished": finished,
        "updated_at": "now()",
    }

    with _sync_lock:
        try:
            response = requests.post(
                f"{SUPABASE_URL}/rest/v1/magazine_progress",
                headers={
                    "apikey": SUPABASE_ANON_KEY,
                    "Authorization": f"Bearer {SUPABASE_ANON_KEY}",
                    "Content-Type": "application/json",
                    "Prefer": "resolution=merge-duplicates",
                },
                json=payload,
                timeout=10,
            )
            response.raise_for_status()
        except Exception as e:
            logging.error(
                "[PROGRESS] خطأ في حفظ التقدم إلى Supabase: %s", e
            )


# ==========================================
# تحويل صفحة PDF إلى صورة
# ==========================================

def render_page(
    page_number: int,
) -> bytes:

    if not os.path.isfile(
        MAGAZINE_PATH
    ):
        raise FileNotFoundError(
            f"لم يتم العثور على ملف المجلة: "
            f"{MAGAZINE_PATH}"
        )

    document = fitz.open(
        MAGAZINE_PATH
    )

    try:

        total_pages = len(document)

        if page_number < 1:
            raise ValueError(
                "رقم الصفحة غير صحيح."
            )

        if page_number > total_pages:
            raise EOFError(
                "انتهت صفحات المجلة."
            )

        page = document[
            page_number - 1
        ]

        scale = PDF_DPI / 72

        matrix = fitz.Matrix(
            scale,
            scale,
        )

        pixmap = page.get_pixmap(
            matrix=matrix,
            alpha=False,
        )

        image_bytes = pixmap.tobytes(
            "jpeg"
        )

        logging.info(
            f"[MAGAZINE] تم تحويل الصفحة "
            f"{page_number} إلى صورة."
        )

        return image_bytes

    finally:

        document.close()


# ==========================================
# استخراج النص من الصورة
# ==========================================

def extract_text_sync(
    image_bytes: bytes,
) -> str:
    import time

    if not groq_client:
        raise RuntimeError(
            "GROQ_API_KEY غير موجود."
        )

    encoded_image = base64.b64encode(
        image_bytes
    ).decode("utf-8")

    # قائمة بالنماذج المتاحة الحديثة والمدعومة للرؤية والنصوص
    models_to_try = [
        GROQ_VISION_MODEL,
        "llama-3.2-11b-vision",
        "llama-3.3-70b-versatile"
    ]
    
    # إزالة التكرارات مع الحفاظ على الترتيب
    seen = set()
    models_to_try = [m for m in models_to_try if m and not (m in seen or seen.add(m))]

    last_exception = None

    for model in models_to_try:
        try:
            logging.info(f"[GROQ] محاولة استخراج النص باستخدام النموذج: {model}")
            response = (
                groq_client
                .chat
                .completions
                .create(
                    model=model,
                    messages=[
                        {
                            "role": "user",
                            "content": [
                                {
                                    "type": "text",
                                    "text": (
                                        "استخرج النص العربي "
                                        "الموجود في هذه الصفحة "
                                        "كما هو تماماً.\n\n"
                                        "مهم جداً:\n"
                                        "- لا تلخص.\n"
                                        "- لا تعيد صياغة.\n"
                                        "- لا تضف أي كلام من عندك.\n"
                                        "- حافظ على ترتيب الفقرات "
                                        "والعناوين قدر الإمكان.\n"
                                        "- لا تكتب وصفاً للصورة.\n"
                                        "- أعد النص فقط."
                                    ),
                                },
                                {
                                    "type": "image_url",
                                    "image_url": {
                                        "url": (
                                            "data:image/jpeg;base64,"
                                            f"{encoded_image}"
                                        )
                                    },
                                },
                            ],
                        }
                    ],
                    temperature=0,
                    max_completion_tokens=4000, # تقليل السقف لمنع استنزاف وتخطي حدود التوكنز المفاجئة
                )
            )

            text = (
                response
                .choices[0]
                .message
                .content
                or ""
            )

            if text.strip():
                return text.strip()

        except Exception as e:
            logging.warning(f"[GROQ] فشل الاستخراج باستخدام النموذج {model}: {e}")
            last_exception = e
            # التهدئة والنوم البرمجي لمنع الحظر الفوري عند الانتقال للنموذج البديل
            logging.info("[GROQ] الانتظار لمدة 5 ثوانٍ لتهدئة الطلبات قبل الانتقال للنموذج التالي...")
            time.sleep(5)

    if last_exception:
        raise last_exception

    return ""


# ==========================================
# استخراج النص بشكل Async
# ==========================================

async def extract_text(
    image_bytes: bytes,
) -> str:

    loop = asyncio.get_running_loop()

    return await loop.run_in_executor(
        None,
        lambda: extract_text_sync(
            image_bytes
        ),
    )


# ==========================================
# إنشاء النص النهائي للمنشور
# ==========================================

def build_text(
    page_number: int,
    extracted_text: str,
) -> str:

    parts = [
        f"📖 {MAGAZINE_TITLE}",
        f"الصفحة {page_number}",
        "",
        extracted_text.strip(),
    ]

    if CHANNEL_LINK:
        parts.extend(
            [
                "",
                "────────────",
                CHANNEL_LINK,
            ]
        )

    return "\n".join(parts)


# ==========================================
# نشر الصفحة التالية (نسخة دمج النص مع الصورة + تقسيم الباقي)
# ==========================================

async def publish_next_page(bot):

    async with _publish_lock:

        progress = load_progress()

        if progress["finished"]:

            logging.info(
                "[MAGAZINE] انتهت المجلة بالكامل."
            )

            return True

        page_number = progress[
            "next_page"
        ]

        logging.info(
            f"[MAGAZINE] بدء تجهيز الصفحة "
            f"{page_number}..."
        )

        try:

            image_bytes = await asyncio.to_thread(
                render_page,
                page_number,
            )

            logging.info(
                f"[MAGAZINE] استخراج نص الصفحة "
                f"{page_number}..."
            )

            extracted_text = (
                await extract_text(
                    image_bytes
                )
            )

            if not extracted_text:

                raise RuntimeError(
                    "Groq لم يعثر على نص في الصفحة."
                )

            logging.info(
                f"[MAGAZINE] تم استخراج النص "
                f"للصفحة {page_number}."
            )

            final_text = build_text(
                page_number,
                extracted_text,
            )

            # --- الحساب الذكي والتقسيم بناءً على قيود تليجرام ---
            MAX_CAPTION_LENGTH = 1000  # الحد الأقصى الآمن لوصف الصورة (تليجرام يسمح بـ 1024)
            MAX_MESSAGE_LENGTH = 4000  # الحد الأقصى الآمن للرسالة النصية العادية (تليجرام يسمح بـ 4096)

            # إذا كان النص الكلي يناسب وصف الصورة بالكامل دون مشاكل
            if len(final_text) <= MAX_CAPTION_LENGTH:
                logging.info(f"[MAGAZINE] نشر الصفحة {page_number} مع كامل النص في وصف الصورة...")
                await bot.send_photo(
                    chat_id=CHANNEL_USERNAME,
                    photo=image_bytes,
                    caption=final_text,
                )
            else:
                logging.info(f"[MAGAZINE] النص طويل؛ سيتم إرفاق جزء مع الصورة وتقسيم المتبقي...")
                
                # استقطاع الجزء الأول الخاص بوصف الصورة مع مراعاة عدم قطع الكلمات
                caption_part = final_text[:MAX_CAPTION_LENGTH]
                # نرجع للخلف حتى نجد آخر مسافة أو سطر جديد لكي لا تنقطع الكلمة في المنتصف
                last_space = max(caption_part.rfind(' '), caption_part.rfind('\n'))
                if last_space > 500:  # للتأكد من عدم الرجوع لمسافة بعيدة جداً
                    caption_part = final_text[:last_space]
                
                # النص المتبقي الذي سيتم توزيعه على رسائل منفصلة
                remaining_text = final_text[len(caption_part):].strip()

                # 1. إرسال المنشور الأول: الصورة ومرفق معها الجزء الأول من النص
                await bot.send_photo(
                    chat_id=CHANNEL_USERNAME,
                    photo=image_bytes,
                    caption=caption_part + "\n\n⬇️ التكملة في الرسالة التالية...",
                )

                # 2. تقسيم وإرسال النص المتبقي في رسائل عادية
                if remaining_text:
                    lines = remaining_text.split('\n')
                    current_chunk = ""
                    part_number = 1
                    
                    for line in lines:
                        # إذا أضيفت السلسلة الحالية وتخطت الحد، نرسل الجزء المجهز أولاً
                        if len(current_chunk) + len(line) + 1 > MAX_MESSAGE_LENGTH:
                            chunk_suffix = f"\n\n(تابع صفحة {page_number} - جزء {part_number})"
                            await bot.send_message(
                                chat_id=CHANNEL_USERNAME,
                                text=current_chunk + chunk_suffix,
                            )
                            current_chunk = line
                            part_number += 1
                        else:
                            if current_chunk:
                                current_chunk += "\n" + line
                            else:
                                current_chunk = line
                    
                    # إرسال الجزء الأخير المتبقي
                    if current_chunk:
                        chunk_suffix = f"\n\n(تابع صفحة {page_number} - الجزء الأخير)" if part_number > 1 else ""
                        await bot.send_message(
                            chat_id=CHANNEL_USERNAME,
                            text=current_chunk + chunk_suffix,
                        )

            document = fitz.open(MAGAZINE_PATH)

            try:

                total_pages = len(
                    document
                )

            finally:

                document.close()

            if page_number >= total_pages:

                save_progress(
                    next_page=page_number + 1,
                    finished=True,
                )

                logging.info(
                    "[MAGAZINE] تم نشر آخر صفحة "
                    "وانتهت المجلة."
                )

            else:

                save_progress(
                    next_page=page_number + 1,
                    finished=False,
                )

                logging.info(
                    f"[MAGAZINE] تم نشر الصفحة "
                    f"{page_number} بنجاح. "
                    f"الصفحة القادمة: "
                    f"{page_number + 1}"
                )

            return True

        except EOFError:

            save_progress(
                next_page=page_number,
                finished=True,
            )

            logging.info(
                "[MAGAZINE] لا توجد صفحات أخرى."
            )
            return True

        except Exception as e:

            logging.exception(
                f"[MAGAZINE] فشل نشر الصفحة "
                f"{page_number}: {e}"
            )
            
            logging.info("[MAGAZINE] سيتم النوم مؤقتاً لمدة 60 ثانية قبل السماح بأي محاولة نشر جديدة...")
            await asyncio.sleep(60)

            return False
