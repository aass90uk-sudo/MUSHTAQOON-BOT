# ==========================================
# إنشاء نص المنشور
# ==========================================

def build_text(
    page_number: int,
    extracted_text: str,
) -> str:

    # الحد الأقصى الذي نريده للمنشور كاملاً
    MAX_CAPTION_LENGTH = 1000

    # الختم والرابط جزء من الـ 1000 حرف
    footer = (
        "بقية تكملة نص الصفحة يوجد في صورة المجلة❤️\n\n"
        "@Athar_Dz_Islamic"
    )

    header = (
        f"📖 {MAGAZINE_TITLE}\n"
        f"الصفحة {page_number}\n\n"
    )

    # تنظيف النص المستخرج فقط
    text = (
        extracted_text
        .strip()
        .replace("\r\n", "\n")
        .replace("\r", "\n")
    )

    # المساحة المتبقية للنص الحقيقي
    available_length = (
        MAX_CAPTION_LENGTH
        - len(header)
        - len(footer)
        - 2
    )

    if available_length < 0:
        raise ValueError(
            "العنوان والختم والرابط يتجاوزون حد 1000 حرف."
        )

    # إذا كان النص أطول من المساحة المتاحة
    # نأخذ أكبر قدر ممكن منه دون تجاوز 1000 حرف
    if len(text) > available_length:

        text_part = text[:available_length]

        # عدم قطع الكلمة في منتصفها
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

    # حماية نهائية: يجب ألا يتجاوز المنشور 1000 حرف
    if len(final_text) > MAX_CAPTION_LENGTH:

        overflow = (
            len(final_text)
            - MAX_CAPTION_LENGTH
        )

        text_part = text_part[
            :max(0, len(text_part) - overflow)
        ].rstrip()

        final_text = (
            header
            + text_part
            + "\n\n"
            + footer
        )

    logging.info(
        f"[MAGAZINE] طول منشور الصفحة "
        f"{page_number}: {len(final_text)} حرف."
    )

    return final_text


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

            return True

        page_number = progress[
            "next_page"
        ]

        logging.info(
            f"[MAGAZINE] بدء تجهيز الصفحة "
            f"{page_number}..."
        )

        try:

            # ==================================
            # تحويل الصفحة إلى صورة
            # ==================================

            image_bytes = await asyncio.to_thread(
                render_page,
                page_number,
            )

            logging.info(
                f"[MAGAZINE] تم تجهيز صورة الصفحة "
                f"{page_number}."
            )

            # ==================================
            # استخراج النص الحقيقي من الصورة
            # ==================================

            logging.info(
                f"[MAGAZINE] استخراج نص الصفحة "
                f"{page_number}..."
            )

            extracted_text = await extract_text(
                image_bytes
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
            # إنشاء المنشور النهائي
            # ==================================

            final_text = build_text(
                page_number,
                extracted_text,
            )

            # ==================================
            # نشر الصورة + النص في منشور واحد
            # ==================================

            logging.info(
                f"[MAGAZINE] نشر الصفحة "
                f"{page_number} مع الصورة والنص..."
            )

            await bot.send_photo(
                chat_id=CHANNEL_USERNAME,
                photo=image_bytes,
                caption=final_text,
            )

            logging.info(
                f"[MAGAZINE] تم نشر الصفحة "
                f"{page_number} بنجاح."
            )

            # ==================================
            # معرفة عدد صفحات المجلة
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
            # حفظ التقدم
            # ==================================

            if page_number >= total_pages:

                save_progress(
                    next_page=page_number + 1,
                    finished=True,
                )

                logging.info(
                    "[MAGAZINE] تم نشر آخر صفحة "
                    "وانتهت المجلة بالكامل."
                )

            else:

                save_progress(
                    next_page=page_number + 1,
                    finished=False,
                )

                logging.info(
                    f"[MAGAZINE] تم حفظ التقدم. "
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

            logging.info(
                "[MAGAZINE] سيتم الانتظار "
                "60 ثانية قبل المحاولة التالية..."
            )

            await asyncio.sleep(60)

            return False
