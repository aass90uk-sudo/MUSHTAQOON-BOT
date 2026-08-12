import asyncio
import logging
import os  # جلب مكتبة النظام لقراءة المتغيرات البيئية من Railway
import fitz  # PyMuPDF

# ==========================================
# قراءة المتغيرات والديناميكية من منصة Railway
# ==========================================
MAGAZINE_TITLE = "مجلة المشتاقون إلى الجنة"

# قراءة اسم المستخدم من بيئة نظام لوحة تحكم Railway أو استخدام القيمة الافتراضية
CHANNEL_USERNAME = os.environ.get("CHANNEL_USERNAME", "@Athar_Dz_Islamic")

# جلب اسم الملف قادماً من لوحة تحكم Railway لتحديد المسار
raw_magazine_file = os.environ.get("MAGAZINE_FILE", "").strip()

# بناء المسار برمجياً ليتوجه بذكاء إلى داخل المجلد الصحيح المعروض في هيكلية GitHub لديك
if not raw_magazine_file:
    MAGAZINE_PATH = os.path.join("magazine.pdf", "المشتاقون_إلى_الجنة.pdf")
elif "magazine.pdf" in raw_magazine_file:
    MAGAZINE_PATH = raw_magazine_file
else:
    # ربط الملف العربي تلقائياً داخل المجلد لمنع خطأ FileNotFoundError
    MAGAZINE_PATH = os.path.join("magazine.pdf", raw_magazine_file)

MAX_CAPTION_LENGTH = 1000

# قفل الأمان لمنع تداخل عمليات النشر المتزامنة
_publish_lock = asyncio.Lock()


# ==========================================
# إنشاء نص المنشور وضمان الأمان للأطوال
# ==========================================
def build_text(
    page_number: int,
    extracted_text: str,
) -> str:
    """
    بناء نص المنشور وضمان عدم تخطي الحد الأقصى للحروف (1000 حرف).
    يتم اقتطاع النص الحقيقي المستخرج من نهاية آخر كلمة كاملة وتذييله بالخاتمة.
    """
    # الختم والرابط جزء من الـ 1000 حرف
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
# نشر الصفحة التالية وإدارة التقدم (تحديث مدمج)
# ==========================================
async def publish_next_page(bot):
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
            logging.info("[MAGAZINE] سيتم الانتظار 60 ثانية قبل المحاولة التالية...")
            await asyncio.sleep(60)
            return False
        
