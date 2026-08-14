import asyncio
import base64
import json
import logging
import os
import re
from typing import Any, Optional

import fitz
from groq import Groq

from config import (
    CHANNEL_STAMP,
    CHANNEL_USERNAME,
    GROQ_API_KEY,
    GROQ_VISION_MODEL,
    MAGAZINE_DIR,
    MAGAZINE_FILE,
    MAX_CAPTION_LENGTH,
    PDF_DPI,
    START_PAGE,
    SUPABASE_ANON_KEY,
    SUPABASE_URL,
)

SYSTEM_PROMPT = """أنت ناسخ نصوص عربية من الصور، ولست مساعداً حوارياً.
اقرأ صفحة مجلة المشتاقون إلى الجنة المرفقة واستخرج الكلمات الظاهرة في الصفحة فقط.

التزم بهذه القواعد دون استثناء:
١. أعد النص العربي الظاهر في الصورة وحده، بالحروف والكلمات كما تظهر.
٢. لا تكتب تفكيراً أو شرحاً أو مقدمة أو خاتمة أو تحية أو أسماء أقسام.
٣. لا تذكر ما تفعله ولا تصف الصورة ولا تكرر التعليمات.
٤. لا تستخدم أي لغة أجنبية أو رموز تنسيق أو وسوم.
٥. إذا كان جزء من الصورة غير واضح، اتركه ولا تخمّن نصاً من عندك.
٦. ابدأ مباشرة بأول كلمة مقروءة من الصفحة.
٧. أعد النص في ألف حرف أو أقل.
"""

RETRY_PROMPT = "اقرأ الكلمات المطبوعة في الصفحة فقط. أعد النص العربي الظاهر وحده، دون شرح أو تفكير أو عناوين."
_META_PHRASES = (
    "أنا مستخرج",
    "مهمتي",
    "شروط صارمة",
    "سأقوم",
    "سأبدأ",
    "لاحظت أن الصورة",
    "النص في الصورة",
    "الصورة مقسمة",
    "سأركز",
    "أستخرج النص",
)

_groq_client: Optional[Groq] = None
_publish_lock = asyncio.Lock()
_PROGRESS_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "progress.json")

try:
    from supabase import Client, create_client
except ImportError:
    Client = Any  # type: ignore[misc,assignment]
    create_client = None

_supabase: Optional[Client] = None


def _resolve_magazine_path() -> str:
    candidates = [MAGAZINE_FILE, os.path.join(MAGAZINE_DIR, MAGAZINE_FILE)]
    if not MAGAZINE_FILE.lower().endswith(".pdf"):
        candidates.append(os.path.join(MAGAZINE_DIR, f"{MAGAZINE_FILE}.pdf"))
    if os.path.isdir(MAGAZINE_DIR):
        candidates.extend(
            os.path.join(MAGAZINE_DIR, name)
            for name in os.listdir(MAGAZINE_DIR)
            if name.lower().endswith(".pdf")
        )
    return next((path for path in candidates if os.path.isfile(path)), candidates[0])


MAGAZINE_PATH = _resolve_magazine_path()


def _get_groq_client() -> Groq:
    global _groq_client
    if _groq_client is None:
        if not GROQ_API_KEY:
            raise RuntimeError("مفتاح خدمة الرؤية غير موجود.")
        _groq_client = Groq(api_key=GROQ_API_KEY)
    return _groq_client


def _get_supabase() -> Optional[Client]:
    global _supabase
    if _supabase is None and create_client and SUPABASE_URL and SUPABASE_ANON_KEY:
        _supabase = create_client(SUPABASE_URL, SUPABASE_ANON_KEY)
    return _supabase


def _load_progress() -> dict[str, Any]:
    client = _get_supabase()
    if client:
        try:
            result = client.table("magazine_progress").select("next_page, finished").eq("id", 1).maybe_single().execute()
            if result.data:
                return result.data
        except Exception:
            logging.exception("تعذر قراءة تقدم المجلة من قاعدة البيانات.")

    try:
        with open(_PROGRESS_FILE, "r", encoding="utf-8") as file:
            return json.load(file)
    except (FileNotFoundError, json.JSONDecodeError):
        return {"next_page": START_PAGE, "finished": False}


def _save_progress(next_page: int, finished: bool) -> None:
    data = {"next_page": next_page, "finished": finished}
    client = _get_supabase()
    if client:
        try:
            client.table("magazine_progress").upsert({"id": 1, **data}).execute()
            return
        except Exception:
            logging.exception("تعذر حفظ تقدم المجلة في قاعدة البيانات.")
    with open(_PROGRESS_FILE, "w", encoding="utf-8") as file:
        json.dump(data, file, ensure_ascii=False)


def render_page(page_number: int) -> bytes:
    if not os.path.isfile(MAGAZINE_PATH):
        raise FileNotFoundError(f"ملف المجلة غير موجود: {MAGAZINE_PATH}")
    document = fitz.open(MAGAZINE_PATH)
    try:
        if page_number < 1 or page_number > len(document):
            raise EOFError(f"الصفحة {page_number} خارج نطاق المجلة.")
        page = document.load_page(page_number - 1)
        scale = PDF_DPI / 72
        return page.get_pixmap(matrix=fitz.Matrix(scale, scale), alpha=False).tobytes("png")
    finally:
        document.close()


def _strip_thinking(value: str) -> str:
    value = re.sub(r"<think>.*?</think>", "", value, flags=re.IGNORECASE | re.DOTALL)
    value = re.sub(r"<think>.*$", "", value, flags=re.IGNORECASE | re.DOTALL)
    value = re.sub(r"</?think>", "", value, flags=re.IGNORECASE)
    return value.strip()


def _clean_ocr(value: str) -> str:
    value = _strip_thinking(value)
    value = re.sub(r"<[^>]*>", "", value)
    value = value.replace("```", "").replace("**", "").replace("*", "")
    lines: list[str] = []
    for line in value.replace("\r", "").split("\n"):
        if re.search(r"[A-Za-z]", line):
            continue
        line = re.sub(r"[\\`#]", "", line).strip()
        if line:
            lines.append(line)
    return "\n".join(lines).strip()


def _is_usable_ocr(value: str) -> bool:
    if not value or any(phrase in value for phrase in _META_PHRASES):
        return False
    return bool(re.search(r"[\u0600-\u06ff]", value))


def _request_ocr(image_url: str, user_prompt: str) -> str:
    response = _get_groq_client().chat.completions.create(
        model=GROQ_VISION_MODEL,
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": user_prompt},
                    {"type": "image_url", "image_url": {"url": image_url}},
                ],
            },
        ],
        temperature=0,
        max_tokens=1400,
    )
    return response.choices[0].message.content or ""


async def extract_text(image_bytes: bytes) -> str:
    image_url = f"data:image/png;base64,{base64.b64encode(image_bytes).decode('ascii')}"
    for attempt in range(2):
        raw = await asyncio.to_thread(_request_ocr, image_url, RETRY_PROMPT if attempt else "استخرج النص العربي المطبوع في الصورة فقط.")
        cleaned = _clean_ocr(raw)
        if _is_usable_ocr(cleaned):
            return cleaned
        logging.warning("تم رفض إجابة الرؤية لأنها ليست نص الصفحة؛ المحاولة %s.", attempt + 1)
    raise RuntimeError("لم تُرجع خدمة الرؤية نصاً صافياً من الصفحة.")


def build_text(extracted_text: str) -> str:
    footer = f"{CHANNEL_USERNAME}\n{CHANNEL_STAMP}"
    separator = "\n\n"
    available = MAX_CAPTION_LENGTH - len(footer) - len(separator)
    text = _clean_ocr(extracted_text)
    if len(text) > available:
        text = text[:available].rsplit(" ", 1)[0].rstrip()
    final_text = f"{text}{separator}{footer}"
    logging.info("طول النص النهائي: %s حرفاً.", len(final_text))
    return final_text


async def publish_next_page(bot: Any) -> bool:
    async with _publish_lock:
        progress = _load_progress()
        if progress.get("finished"):
            return True

        page_number = int(progress.get("next_page", START_PAGE))
        image_bytes = await asyncio.to_thread(render_page, page_number)
        extracted_text = await extract_text(image_bytes)
        caption = build_text(extracted_text)
        await bot.send_photo(chat_id=CHANNEL_USERNAME, photo=image_bytes, caption=caption)

        document = fitz.open(MAGAZINE_PATH)
        try:
            finished = page_number >= len(document)
        finally:
            document.close()
        _save_progress(page_number if finished else page_number + 1, finished)
        return True
    
