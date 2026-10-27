import os
import asyncio
import logging
import yt_dlp

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    ContextTypes,
    filters,
)

TOKEN = os.getenv("BOT_TOKEN")

logging.basicConfig(level=logging.INFO)

# حفظ خيارات كل مستخدم
user_urls = {}


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "🎬 أهلاً بك في بوت تحميل الفيديو والصوت!\n\n"
        "أرسل رابط فيديو يوتيوب للبدء."
    )


async def handle_url(update: Update, context: ContextTypes.DEFAULT_TYPE):
    url = update.message.text.strip()

    if "youtube.com/" not in url and "youtu.be/" not in url:
        await update.message.reply_text("❌ أرسل رابط يوتيوب صحيحًا.")
        return

    user_urls[update.effective_user.id] = url

    keyboard = [
        [
            InlineKeyboardButton("360p", callback_data="video_360"),
            InlineKeyboardButton("480p", callback_data="video_480"),
        ],
        [
            InlineKeyboardButton("720p", callback_data="video_720"),
            InlineKeyboardButton("1080p", callback_data="video_1080"),
        ],
        [
            InlineKeyboardButton("🎵 صوت MP3", callback_data="audio_mp3"),
        ],
    ]

    await update.message.reply_text(
        "اختر الجودة أو الصيغة المطلوبة:",
        reply_markup=InlineKeyboardMarkup(keyboard),
    )


async def download(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    url = user_urls.get(query.from_user.id)

    if not url:
        await query.edit_message_text("أرسل رابط الفيديو مرة أخرى.")
        return

    choice = query.data

    await query.edit_message_text("⏳ جاري تجهيز التحميل، انتظر...")

    try:
        if choice == "audio_mp3":
            options = {
                "format": "bestaudio/best",
                "outtmpl": "/tmp/%(id)s.%(ext)s",
                "noplaylist": True,
                "postprocessors": [{
                    "key": "FFmpegExtractAudio",
                    "preferredcodec": "mp3",
                    "preferredquality": "192",
                }],
            }
        else:
            quality = choice.split("_")[1]
            options = {
                "format": f"best[height<={quality}][ext=mp4]/best[height<={quality}]",
                "outtmpl": "/tmp/%(id)s.%(ext)s",
                "noplaylist": True,
            }

        def get_video():
            with yt_dlp.YoutubeDL(options) as ydl:
                info = ydl.extract_info(url, download=True)
                return ydl.prepare_filename(info), info.get("title", "video")

        path, title = await asyncio.to_thread(get_video)

        if choice == "audio_mp3":
            path = os.path.splitext(path)[0] + ".mp3"

        if not os.path.exists(path):
            await query.message.reply_text(
                "تعذر العثور على الملف بعد التحميل."
            )
            return

        if os.path.getsize(path) > 49 * 1024 * 1024:
            await query.message.reply_text(
                "حجم الملف أكبر من الحد المسموح للإرسال عبر هذه الطريقة."
            )
            return

        await query.message.reply_text_document(
            document=open(path, "rb"),
            filename=os.path.basename(path),
            read_timeout=120,
            write_timeout=120,
        )

        os.remove(path)

    except Exception as e:
        logging.exception("Download failed")
        await query.message.reply_text(
            "❌ فشل التحميل. قد يكون الفيديو غير متاح أو الجودة غير مدعومة."
        )


def main():
    if not TOKEN:
        raise RuntimeError("أضف توكن البوت في متغير BOT_TOKEN.")

    app = Application.builder().token(TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(
        MessageHandler(filters.TEXT & ~filters.COMMAND, handle_url)
    )
    app.add_handler(CallbackQueryHandler(download))

    print("Bot is running...")
    app.run_polling()


if __name__ == "__main__":
    main()
