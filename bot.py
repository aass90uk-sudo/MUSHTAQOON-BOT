import asyncio
import logging

from telegram.ext import Application
from apscheduler.schedulers.asyncio import AsyncIOScheduler
import pytz

from config import TELEGRAM_TOKEN, TIMEZONE
from magazine import publish_next_page


# ==========================================
# Logging
# ==========================================

print("========== STARTING MUSHTAQOON BOT ==========")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
    force=True,
)

logging.info("========== BOT STARTED ==========")


async def verify_configuration(bot) -> None:
    """Fail early with an actionable message instead of a silent retry."""
    from config import CHANNEL_USERNAME, GROQ_API_KEY
    from magazine import MAGAZINE_PATH
    import os

    if not CHANNEL_USERNAME:
        raise RuntimeError("CHANNEL_USERNAME غير موجود.")
    if not GROQ_API_KEY:
        raise RuntimeError("GROQ_API_KEY غير موجود.")
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


async def publish_on_startup(application: Application) -> None:
    """Try the first page more than once so transient API errors recover."""
    for attempt in range(1, 4):
        try:
            published = await publish_next_page(application.bot)
            if published:
                return
            logging.warning(
                "[STARTUP] النشر لم يكتمل، ستتم إعادة المحاولة."
            )
        except Exception:
            logging.exception(
                "[STARTUP] محاولة النشر %s/3 فشلت.",
                attempt,
            )

        if attempt < 3:
            await asyncio.sleep(10 * attempt)


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
        logging.info("تشغيل النشر الأول...")
        await publish_on_startup(application)
    except Exception as e:
        logging.exception(
            "[STARTUP] تعذر بدء النشر: %s",
            e,
        )

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
        publish_next_page,
        "cron",
        hour=6,
        minute=0,
        args=[application.bot],
        id="morning_magazine",
        replace_existing=True,
    )

    # ======================================
    # النشر المسائي
    # ======================================

    scheduler.add_job(
        publish_next_page,
        "cron",
        hour=20,
        minute=0,
        args=[application.bot],
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
