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


# ==========================================
# الجدولة
# ==========================================

async def post_init(application: Application) -> None:
    """
    تشغيل النشر الأول فور تشغيل البوت،
    ثم جدولة النشر الساعة 06:00 و20:00 بتوقيت مكة.
    """

    logging.info("تشغيل اختبار النشر الأول...")

    try:
        await publish_next_page(application.bot)
    except Exception as e:
        logging.exception(
            f"فشل النشر الأول: {e}"
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
