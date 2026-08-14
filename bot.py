import asyncio
import logging
import sys

from telegram.ext import Application
from apscheduler.schedulers.asyncio import AsyncIOScheduler
import pytz

from config import PUBLISH_RETRIES, TELEGRAM_TOKEN, TIMEZONE
from magazine import publish_next_page

# ==========================================
# Logging
# ==========================================

print("========== STARTING MUSHTAQOON BOT ==========")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
    stream=sys.stdout,
    force=True,
)

logging.info("========== BOT STARTED ==========")

async def verify_configuration(bot) -> None:
    """Fail early with an actionable message instead of a silent retry."""
    from config import CHANNEL_USERNAME
    from magazine import MAGAZINE_PATH
    import os

    if not CHANNEL_USERNAME:
        raise RuntimeError("CHANNEL_USERNAME غير موجود.")
    if not os.path.isfile(MAGAZINE_PATH):
        raise FileNotFoundError(
            f"ملف المجلة غير موجود: {MAGAZINE_PATH}. "
            "تحقق من MAGAZINE_FILE وMAGAZINE_DIR."
        )

    me = await bot.get_me()
    chat = await bot.get_chat(CHANNEL_USERNAME)
    member = await bot.get_chat_member(chat.id, me.id)

    if member.status not in {"administrator", "creator"}:
        raise RuntimeError(
            f"البوت ليس مشرفاً في القناة {chat.title or CHANNEL_USERNAME}. "
            "أضفه كمسؤول مع صلاحية نشر الرسائل والصور."
        )

    logging.info(
        "[CHECK] Telegram OK: @%s -> %s",
        me.username or me.id,
        chat.title or CHANNEL_USERNAME,
    )
    logging.info("[CHECK] Magazine OK: %s", MAGAZINE_PATH)

async def publish_with_retries(bot, source: str) -> None:
    """Retry a post after temporary Telegram or network failures."""
    for attempt in range(1, PUBLISH_RETRIES + 1):
        try:
            if await publish_next_page(bot):
                return
        except Exception:
            logging.exception(
                "[%s] محاولة النشر %s/%s فشلت.",
                source,
                attempt,
                PUBLISH_RETRIES,
            )

        if attempt < PUBLISH_RETRIES:
            delay = 15 * attempt
            logging.warning(
                "[%s] ستتم إعادة المحاولة بعد %s ثانية.",
                source,
                delay,
            )
            await asyncio.sleep(delay)

    logging.error(
        "[%s] تعذر النشر بعد %s محاولات؛ ستستمر الجدولة.",
        source,
        PUBLISH_RETRIES,
    )

async def publish_on_startup(application: Application) -> None:
    await publish_with_retries(application.bot, "STARTUP")

# ==========================================
# الجدولة
# ==========================================

async def post_init(application: Application) -> None:
    """
    تشغيل النشر الأول فور تشغيل البوت،
    ثم جدولة النشر الساعة 06:00 و20:00 بتوقيت مكة.
    """

    try:
        await verify_configuration(application.bot)
    except Exception as e:
        logging.exception("[CHECK] فشل فحص الإعدادات: %s", e)

    logging.info("تشغيل النشر الأول...")
    await publish_on_startup(application)

    # ======================================
    # توقيت مكة
    # ======================================

    timezone = pytz.timezone(TIMEZONE)

    scheduler = AsyncIOScheduler(
        timezone=timezone
    )

    # ======================================
    # النشر الصباحي
    # ======================================

    scheduler.add_job(
        publish_with_retries,
        "cron",
        hour=6,
        minute=0,
        args=[application.bot, "MORNING"],
        id="morning_magazine",
        replace_existing=True,
    )

    # ======================================
    # النشر المسائي
    # ======================================

    scheduler.add_job(
        publish_with_retries,
        "cron",
        hour=20,
        minute=0,
        args=[application.bot, "EVENING"],
        id="evening_magazine",
        replace_existing=True,
    )

    scheduler.start()

    application.bot_data["scheduler"] = scheduler

    logging.info(
        "تم تشغيل الجدولة."
    )

    logging.info(
        "النشر الصباحي: 06:00 بتوقيت مكة."
    )

    logging.info(
        "النشر المسائي: 20:00 بتوقيت مكة."
    )

# ==========================================
# إيقاف الجدولة
# ==========================================

async def post_stop(application: Application) -> None:

    scheduler = application.bot_data.get(
        "scheduler"
    )

    if scheduler and scheduler.running:

        scheduler.shutdown()

        logging.info(
            "تم إيقاف الجدولة بأمان."
        )

# ==========================================
# تشغيل البوت
# ==========================================

def main():

    if not TELEGRAM_TOKEN:
        raise RuntimeError(
            "TELEGRAM_TOKEN غير موجود."
        )

    logging.info(
        "جاري إنشاء تطبيق Telegram..."
    )

    application = (
        Application.builder()
        .token(TELEGRAM_TOKEN)
        .post_init(post_init)
        .post_stop(post_stop)
        .build()
    )

    logging.info(
        "البوت يعمل..."
    )

    application.run_polling(
        drop_pending_updates=True
    )

# ==========================================
# نقطة البداية
# ==========================================

if __name__ == "__main__":
    main()
            
