import os
import base64
import asyncio
import logging
import threading
import glob
import re

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
# إعدادات النشر
# ==========================================

# الحد الأقصى للنص المستخرج المستخدم في منشور الصورة.
# نترك مساحة كافية للعنوان والختم والرابط حتى لا نتجاوز
# حد Telegram البالغ 1024 حرفاً.
MAX_POST_LENGTH = 1000

# الختم الثابت المطلوب في نهاية المنشور.
CONTINUATION_TEXT = "بقية تكملة نص الصفحة يوجد في صورة المجلة❤️"

# رابط القناة الثابت.
CHANNEL_FOOTER = "@Athar_Dz_Islamic"


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
    """العثور على ملف PDF حتى لو كان المسار نسبياً."""

    configured_path = os.path.expanduser(
        MAGAZINE_FILE.strip()
    )

    candidates = [
        configured_path
    ]

    if not os.path.isabs(
        configured_path
    ):
        candidates.insert(
            0,
            os.path.join(
                MAGAZINE_DIR,
                configured_path,
            ),
        )

    for candidate in candidates:
        if os.path.isfile(candidate):
            return candidate

    pdf_files = sorted(
        glob.glob(
            os.path.join(
                MAGAZINE_DIR,
                "*.pdf",
            )
        )
    )

    if len(pdf_files) == 1:

        logging.warning(
            "[MAGAZINE] MAGAZINE_FILE لم يطابق الاسم تماماً؛ "
            "سيتم استخدام: %s",
            pdf_files[0],
        )

        return pdf_files[0]

    return candidates[0]


MAGAZINE_PATH = resolve_magazine_path()


# ==========================================
# قراءة تقدم المجلة من Supabase
# ==========================================

def load_progress():

    fallback = {
        "next_page": START_PAGE,
        "finished": False,
    }

    if (
        not SUPABASE_URL
        or not SUPABASE_ANON_KEY
    ):

        logging.warning(
            "[PROGRESS] Supabase غير مضبوط؛ "
            "البدء من START_PAGE=%s",
            START_PAGE,
        )

        return fallback

    try:

        response = requests.get(
            f"{SUPABASE_URL}/rest/v1/magazine_progress?id=eq.1",
            headers={
                "apikey": SUPABASE_ANON_KEY,
                "Authorization": (
                    f"Bearer {SUPABASE_ANON_KEY}"
                ),
            },
            timeout=10,
        )

        response.raise_for_status()

        rows = response.json()

        if not rows:

            logging.info(
                "[PROGRESS] لا يوجد سجل تقدم؛ "
                "البدء من الصفحة %s.",
                START_PAGE,
            )

            return fallback

        row = rows[0]

        return {
            "next_page": int(
                row["next_page"]
            ),
            "finished": bool(
                row["finished"]
            ),
        }

    except Exception as e:

        logging.error(
            "[PROGRESS] فشل قراءة التقدم: %s",
            e,
        )

        return fallback


# ==========================================
# حفظ تقدم المجلة
# ==========================================

def save_progress(
    next_page: int,
    finished: bool = False,
):

    if (
        not SUPABASE_URL
        or not SUPABASE_ANON_KEY
    ):

        logging.warning(
            "[PROGRESS] لا يمكن حفظ التقدم؛ "
            "Supabase غير مضبوط."
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
                    "Authorization": (
                        f"Bearer {SUPABASE_ANON_KEY}"
                    ),
                    "Content-Type": (
                        "application/json"
                    ),
                    "Prefer": (
                        "resolution=merge-duplicates"
                    ),
                },
                json=payload,
                timeout=10,
            )

            response.raise_for_status()

            logging.info(
                "[PROGRESS] تم حفظ التقدم: الصفحة القادمة %s",
                next_page,
            )

        except Exception as e:

            logging.error(
                "[PROGRESS] فشل حفظ التقدم: %s",
                e,
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
            "لم يتم العثور على ملف المجلة: "
            f"{MAGAZINE_PATH}"
        )

    document = fitz.open(
        MAGAZINE_PATH
    )

    try:

        total_pages = len(
            document
        )

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
            "[MAGAZINE] تم تحويل الصفحة %s إلى صورة.",
            page_number,
        )

        return image_bytes

    finally:

        document.close()


# ==========================================
# تنظيف النص المستخرج
# ==========================================

def clean_extracted_text(
    text: str,
) -> str:

    if not text:
        return ""

    text = text.strip()

    # إزالة Markdown الذي قد يضيفه النموذج.
    text = re.sub(
        r"```.*?```",
        "",
        text,
        flags=re.DOTALL,
    )

    text = text.replace(
        "**",
        "",
    )

    text = text.replace(
        "__",
        "",
    )

    # حذف بعض العبارات التي تدل على أن النموذج
    # بدأ يتحدث بدلاً من نسخ النص.
    forbidden_prefixes = [
        "here is",
        "here's",
        "here is the text",
        "the text is",
        "transcription:",
        "ocr:",
        "sure",
        "certainly",
        "النص المستخرج:",
        "إليك النص:",
        "هذا هو النص:",
    ]

    lines = []

    for line in text.splitlines():

        stripped = line.strip()

        if not stripped:
            lines.append("")
            continue

        lower_line = stripped.lower()

        if any(
            lower_line.startswith(prefix)
            for prefix in forbidden_prefixes
        ):
            continue

        lines.append(
            stripped
        )

    text = "\n".join(
        lines
    ).strip()

    return text


# ==========================================
# استخراج النص من الصورة عبر Groq Vision
# ==========================================

def extract_text_sync(
    image_bytes: bytes,
) -> str:

    if not groq_client:

        raise RuntimeError(
            "GROQ_API_KEY غير موجود."
        )

    encoded_image = base64.b64encode(
        image_bytes
    ).decode(
        "utf-8"
    )

    # النموذج الحالي للرؤية.
    models_to_try = [
        GROQ_VISION_MODEL,
        "meta-llama/llama-4-scout-17b-16e-instruct",
        "qwen/qwen3.6-27b",
    ]

    # إزالة التكرارات.
    seen = set()

    models_to_try = [
        model
        for model in models_to_try
        if model
        and not (
            model in seen
            or seen.add(model)
        )
    ]

    last_exception = None

    for model in models_to_try:

        try:

            logging.info(
                "[GROQ] استخراج النص باستخدام: %s",
                model,
            )

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
                                        "مهمتك الوحيدة هي نسخ "
                                        "النص الموجود داخل صورة "
                                        "صفحة المجلة.\n\n"

                                        "قواعد صارمة جداً:\n"
                                        "1. انسخ النص الموجود في "
                                        "الصورة فقط.\n"
                                        "2. ممنوع التأليف أو "
                                        "التخمين أو التلخيص.\n"
                                        "3. ممنوع كتابة مقدمة أو "
                                        "شرح أو تعليق.\n"
                                        "4. ممنوع كتابة أي جملة "
                                        "مثل Here is أو The text is.\n"
                                        "5. لا تضف أي نص غير موجود "
                                        "في الصورة.\n"
                                        "6. حافظ على النص العربي "
                                        "وترتيب الفقرات قدر الإمكان.\n"
                                        "7. أعد النص المنسوخ فقط "
                                        "بدون أي كلام إضافي."
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
                    max_completion_tokens=4000,
                )
            )

            text = (
                response
                .choices[0]
                .message
                .content
                or ""
            )

            text = clean_extracted_text(
                text
            )

            if text:

                logging.info(
                    "[GROQ] تم استخراج نص الصفحة بنجاح."
                )

                return text

        except Exception as e:

            logging.warning(
                "[GROQ] فشل النموذج %s: %s",
                model,
                e,
            )

            last_exception = e

    if last_exception:

        raise last_exception

    return ""


# ==========================================
# استخراج النص Async
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
# بناء منشور الصورة
# ==========================================

def build_caption(
    page_number: int,
    extracted_text: str,
) -> str:

    # الختم والرابط ثابتان ولا يأتيان من النموذج.
    footer = (
        "\n\n"
        "❤️ بقية تكملة نص الصفحة يوجد في صورة المجلة"
        "\n"
        f"{CHANNEL_FOOTER}"
    )

    header = (
        f"📖 {MAGAZINE_TITLE}"
        f"\n"
        f"الصفحة {page_number}"
        f"\n\n"
    )

    # Telegram يسمح بحد أقصى 1024 حرفاً للكابشن.
    # نحن نستهدف 1000 حرف كحد أقصى للمنشور كاملاً.
    available_for_text = (
        MAX_POST_LENGTH
        - len(header)
        - len(footer)
    )

    if available_for_text < 0:
        available_for_text = 0

    text = extracted_text.strip()

    # نحاول ألا نقطع كلمة في منتصفها.
    if len(text) > available_for_text:

        candidate = text[
            :available_for_text
        ]

        last_space = max(
            candidate.rfind(" "),
            candidate.rfind("\n"),
        )

        if last_space > 0:

            candidate = candidate[
                :last_space
            ]

        text = candidate.strip()

    caption = (
        header
        + text
        + footer
    )

    # حماية نهائية.
    if len(caption) > MAX_POST_LENGTH:

        caption = caption[
            :MAX_POST_LENGTH
        ]

    return caption


# ==========================================
# نشر الصفحة التالية
# ==========================================

async def publish_next_page(
    bot,
):

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
            "[MAGAZINE] تجهيز الصفحة %s...",
            page_number,
        )

        try:

            # ----------------------------------
            # 1. تحويل الصفحة إلى صورة
            # ----------------------------------

            image_bytes = await asyncio.to_thread(
                render_page,
                page_number,
            )

            # ----------------------------------
            # 2. استخراج النص الحقيقي
            # ----------------------------------

            logging.info(
                "[MAGAZINE] استخراج نص الصفحة %s...",
                page_number,
            )

            extracted_text = await extract_text(
                image_bytes
            )

            if not extracted_text:

                raise RuntimeError(
                    "لم يتم استخراج أي نص من الصفحة."
                )

            # ----------------------------------
            # 3. بناء الكابشن
            # ----------------------------------

            caption = build_caption(
                page_number,
                extracted_text,
            )

            logging.info(
                "[MAGAZINE] طول المنشور النهائي: %s حرف.",
                len(caption),
            )

            # ----------------------------------
            # 4. نشر الصورة + النص في منشور واحد
            # ----------------------------------

            await bot.send_photo(
                chat_id=CHANNEL_USERNAME,
                photo=image_bytes,
                caption=caption,
            )

            logging.info(
                "[MAGAZINE] تم نشر الصفحة %s بنجاح.",
                page_number,
            )

            # ----------------------------------
            # 5. معرفة عدد صفحات المجلة
            # ----------------------------------

            document = fitz.open(
                MAGAZINE_PATH
            )

            try:

                total_pages = len(
                    document
                )

            finally:

                document.close()

            # ----------------------------------
            # 6. حفظ الصفحة التالية
            # ----------------------------------

            if page_number >= total_pages:

                save_progress(
                    next_page=page_number + 1,
                    finished=True,
                )

                logging.info(
                    "[MAGAZINE] تم نشر آخر صفحة."
                )

            else:

                save_progress(
                    next_page=page_number + 1,
                    finished=False,
                )

                logging.info(
                    "[MAGAZINE] الصفحة القادمة: %s",
                    page_number + 1,
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
                "[MAGAZINE] فشل نشر الصفحة %s: %s",
                page_number,
                e,
            )

            return False
