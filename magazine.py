import os
import json
import base64
import asyncio
import logging
import threading

import fitz
from groq import Groq

from config import (
    GROQ_API_KEY,
    GROQ_VISION_MODEL,
    MAGAZINE_FILE,
    MAGAZINE_DIR,
    PROGRESS_FILE,
    PDF_DPI,
    MAGAZINE_TITLE,
    CHANNEL_USERNAME,
    CHANNEL_LINK,
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

MAGAZINE_PATH = os.path.join(
    MAGAZINE_DIR,
    MAGAZINE_FILE,
)


# ==========================================
# التأكد من مجلد البيانات
# ==========================================

def ensure_data_dir():

    directory = os.path.dirname(
        PROGRESS_FILE
    )

    if directory:
        os.makedirs(
            directory,
            exist_ok=True,
        )


# ==========================================
# قراءة التقدم
# ==========================================

def load_progress():

    ensure_data_dir()

    if not os.path.exists(
        PROGRESS_FILE
    ):
        return {
            "next_page": 1,
            "finished": False,
        }

    try:

        with open(
            PROGRESS_FILE,
            "r",
            encoding="utf-8",
        ) as file:

            data = json.load(file)

        return {
            "next_page": int(
                data.get(
                    "next_page",
                    1,
                )
            ),
            "finished": bool(
                data.get(
                    "finished",
                    False,
                )
            ),
        }

    except Exception as e:

        logging.error(
            f"خطأ في قراءة progress.json: {e}"
        )

        return {
            "next_page": 1,
            "finished": False,
        }


# ==========================================
# حفظ التقدم
# ==========================================

def save_progress(
    next_page: int,
    finished: bool = False,
):

    ensure_data_dir()

    temporary_file = (
        f"{PROGRESS_FILE}.tmp"
    )

    data = {
        "next_page": next_page,
        "finished": finished,
    }

    with _sync_lock:

        with open(
            temporary_file,
            "w",
            encoding="utf-8",
        ) as file:

            json.dump(
                data,
                file,
                ensure_ascii=False,
                indent=2,
            )

        os.replace(
            temporary_file,
            PROGRESS_FILE,
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

    if not groq_client:
        raise RuntimeError(
            "GROQ_API_KEY غير موجود."
        )

    encoded_image = base64.b64encode(
        image_bytes
    ).decode("utf-8")

    response = (
        groq_client
        .chat
        .completions
        .create(
            model=GROQ_VISION_MODEL,
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
            max_completion_tokens=8000,
        )
    )

    text = (
        response
        .choices[0]
        .message
        .content
        or ""
    )

    return text.strip()


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
# نشر الصفحة التالية
# ==========================================

async def publish_next_page(bot):

    async with _publish_lock:

        progress = load_progress()

        if progress["finished"]:

            logging.info(
                "[MAGAZINE] انتهت المجلة بالكامل."
            )

            return

        page_number = progress[
            "next_page"
        ]

        logging.info(
            f"[MAGAZINE] بدء تجهيز الصفحة "
            f"{page_number}..."
        )

        try:

            # ==================================
            # تحويل الصفحة
            # ==================================

            image_bytes = await asyncio.to_thread(
                render_page,
                page_number,
            )

            # ==================================
            # استخراج النص
            # ==================================

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

            # ==================================
            # تجهيز المنشور
            # ==================================

            final_text = build_text(
                page_number,
                extracted_text,
            )

            # ==================================
            # إرسال الصورة
            # ==================================

            logging.info(
                f"[MAGAZINE] نشر الصفحة "
                f"{page_number}..."
            )

            await bot.send_photo(
                chat_id=CHANNEL_USERNAME,
                photo=image_bytes,
            )

            # ==================================
            # إرسال النص
            # ==================================

            await bot.send_message(
                chat_id=CHANNEL_USERNAME,
                text=final_text,
            )

            # ==================================
            # معرفة عدد الصفحات
            # ==================================

            document = fitz.open(
                MAGAZINE_PATH
            )

            try:
                total_pages = len(
                    document
                )
            finally:
                document.close()

            # ==================================
            # حفظ التقدم بعد نجاح النشر
            # ==================================

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

        except EOFError:

            save_progress(
                next_page=page_number,
                finished=True,
            )

            logging.info(
                "[MAGAZINE] لا توجد صفحات أخرى."
            )

        except Exception as e:

            logging.exception(
                f"[MAGAZINE] فشل نشر الصفحة "
                f"{page_number}: {e}"
            )

            # لا نزيد رقم الصفحة عند الفشل.
            # ستتم محاولة نفس الصفحة مرة أخرى.
            return
