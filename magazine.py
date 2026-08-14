import asyncio
import json
import logging
import os
from typing import Any, Optional

import fitz

from config import (
    CHANNEL_STAMP,
    CHANNEL_USERNAME,
    MAGAZINE_DIR,
    MAGAZINE_FILE,
    PDF_DPI,
    START_PAGE,
    SUPABASE_ANON_KEY,
    SUPABASE_URL,
)

_publish_lock = asyncio.Lock()
_PROGRESS_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "progress.json")

try:
    from Bolt Database import Client, create_client
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

def build_caption() -> str:
    """توقيع القناة والختم فقط، دون نص الصفحة."""
    return f"{CHANNEL_USERNAME}\n{CHANNEL_STAMP}"

async def publish_next_page(bot: Any) -> bool:
    async with _publish_lock:
        progress = _load_progress()
        if progress.get("finished"):
            return True

        page_number = int(progress.get("next_page", START_PAGE))
        image_bytes = await asyncio.to_thread(render_page, page_number)
        caption = build_caption()
        await bot.send_photo(chat_id=CHANNEL_USERNAME, photo=image_bytes, caption=caption)

        document = fitz.open(MAGAZINE_PATH)
        try:
            finished = page_number >= len(document)
        finally:
            document.close()
        _save_progress(page_number if finished else page_number + 1, finished)
        return True
        
