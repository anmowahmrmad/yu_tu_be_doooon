import os
import re
import json
import time
import asyncio
import logging
import tempfile
from pathlib import Path

import yt_dlp
from telegram import (
    Update,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    ReplyKeyboardMarkup,
)
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    ContextTypes,
    filters,
)

# =========================
# إعدادات البوت
# =========================

TOKEN = os.getenv("BOT_TOKEN", "").strip()
OWNER_ID = int(os.getenv("OWNER_ID", "0"))

DATA_DIR = Path(os.getenv("DATA_DIR", "data"))
DATA_DIR.mkdir(parents=True, exist_ok=True)

DB_FILE = DATA_DIR / "bot_data.json"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)

# حالات لوحة المالك
OWNER_STATES = {}
USER_STATES = {}

# قفل لحماية حفظ البيانات
DB_LOCK = asyncio.Lock()


def load_db():
    if DB_FILE.exists():
        try:
            data = json.loads(DB_FILE.read_text(encoding="utf-8"))
        except Exception:
            logger.exception("تعذر قراءة قاعدة البيانات")
            data = {}
    else:
        data = {}

    data.setdefault("users", [])
    data.setdefault("settings", {
        "forward_enabled": False,
    })
    data.setdefault("message_map", {})
    data.setdefault("next_message_id", 1)

    return data


DB = load_db()


async def save_db():
    async with DB_LOCK:
        temp_file = DB_FILE.with_suffix(".tmp")
        temp_file.write_text(
            json.dumps(DB, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        temp_file.replace(DB_FILE)


def main_keyboard():
    return ReplyKeyboardMarkup(
        [
            ["🎬 تحميل من يوتيوب"],
            ["👨‍💻 مراسلة المالك"],
        ],
        resize_keyboard=True,
    )


def owner_keyboard():
    forwarding = DB["settings"].get("forward_enabled", False)
    forward_text = (
        "🔴 إيقاف تحويل الرسائل"
        if forwarding
        else "🟢 تشغيل تحويل الرسائل"
    )

    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton(
                "📢 إذاعة للكل",
                callback_data="admin_broadcast",
            ),
        ],
        [
            InlineKeyboardButton(
                "👥 عدد المستخدمين",
                callback_data="admin_users",
            ),
        ],
        [
            InlineKeyboardButton(
                forward_text,
                callback_data="admin_forward_toggle",
            ),
        ],
        [
            InlineKeyboardButton(
                "❌ إلغاء العملية الحالية",
                callback_data="admin_cancel",
            ),
        ],
    ])


def video_keyboard():
    return InlineKeyboardMarkup([
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
    ])


async def register_user(user):
    if not user:
        return

    uid = user.id
    existing = {
        int(item["id"])
        for item in DB["users"]
        if "id" in item
    }

    if uid not in existing:
        DB["users"].append({
            "id": uid,
            "name": user.full_name or "",
            "username": user.username or "",
            "joined": int(time.time()),
        })
        await save_db()


def is_owner(user_id):
    return OWNER_ID != 0 and user_id == OWNER_ID


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    await register_user(user)

    await update.effective_message.reply_text(
        "مرحبًا بك في بوت تحميل يوتيوب! 🎬\n\n"
        "أرسل رابط فيديو يوتيوب، ثم اختر الجودة أو صيغة الصوت.\n\n"
        "يمكنك أيضًا مراسلة مالك البوت من الزر أدناه.",
        reply_markup=main_keyboard(),
    )


async def admin_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user

    if not is_owner(user.id):
        await update.effective_message.reply_text("غير مسموح لك.")
        return

    OWNER_STATES.pop(user.id, None)

    await update.effective_message.reply_text(
        "👑 لوحة تحكم المالك\n\nاختر العملية المطلوبة:",
        reply_markup=owner_keyboard(),
    )


async def admin_callback(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):
    query = update.callback_query
    user_id = query.from_user.id

    if not is_owner(user_id):
        await query.answer("هذه اللوحة خاصة بالمالك فقط.", show_alert=True)
        return

    await query.answer()
    action = query.data

    if action == "admin_users":
        count = len(DB["users"])
        await query.message.reply_text(
            f"👥 عدد المستخدمين المسجلين: {count}"
        )

    elif action == "admin_forward_toggle":
        current = DB["settings"].get("forward_enabled", False)
        DB["settings"]["forward_enabled"] = not current
        await save_db()

        state = (
            "تم تشغيل تحويل رسائل المستخدمين إليك ✅"
            if not current
            else "تم إيقاف تحويل رسائل المستخدمين إليك 🔕"
        )

        await query.message.reply_text(
            state,
            reply_markup=owner_keyboard(),
        )

    elif action == "admin_broadcast":
        OWNER_STATES[user_id] = "broadcast"
        await query.message.reply_text(
            "📢 أرسل الآن الرسالة التي تريد إذاعتها لجميع المستخدمين.\n\n"
            "يمكنك إرسال نص أو صورة مع وصفها أو فيديو أو ملف.\n"
            "لإلغاء العملية اضغط زر الإلغاء في لوحة المالك."
        )

    elif action == "admin_cancel":
        OWNER_STATES.pop(user_id, None)
        await query.message.reply_text(
            "تم إلغاء العملية.",
            reply_markup=owner_keyboard(),
        )


async def handle_owner_broadcast(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):
    message = update.effective_message
    owner_id = update.effective_user.id

    if OWNER_STATES.get(owner_id) != "broadcast":
        return False

    OWNER_STATES.pop(owner_id, None)

    status = await message.reply_text("⏳ جارٍ إرسال الإذاعة...")

    success = 0
    failed = 0

    for item in list(DB["users"]):
        uid = int(item["id"])

        try:
            await context.bot.copy_message(
                chat_id=uid,
                from_chat_id=message.chat_id,
                message_id=message.message_id,
            )
            success += 1
        except Exception as exc:
            failed += 1
            logger.info("فشل إرسال الإذاعة إلى %s: %s", uid, exc)

        # لتخفيف الضغط وتجنب حدود تيليجرام
        await asyncio.sleep(0.05)

    await status.edit_text(
        "✅ انتهت الإذاعة.\n\n"
        f"وصلت إلى: {success}\n"
        f"تعذر إرسالها إلى: {failed}"
    )

    return True


async def handle_user_contact(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):
    message = update.effective_message
    user = update.effective_user

    if not is_owner(user.id):
        USER_STATES[user.id] = "contact_owner"

        await message.reply_text(
            "💬 أرسل رسالتك الآن، وستصل إلى مالك البوت.\n"
            "يمكنك إرسال نص أو صورة أو ملف.",
            reply_markup=ReplyKeyboardMarkup(
                [["❌ إلغاء المراسلة"]],
                resize_keyboard=True,
            ),
        )
        return


async def handle_owner_reply(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):
    message = update.effective_message
    user = update.effective_user

    if not is_owner(user.id):
        return False

    # يرد المالك على الرسالة المعاد توجيهها باستخدام Reply
    if not message.reply_to_message:
        return False

    replied_id = message.reply_to_message.message_id
    target_id = DB["message_map"].get(str(replied_id))

    if not target_id:
        return False

    try:
        await context.bot.copy_message(
            chat_id=int(target_id),
            from_chat_id=message.chat_id,
            message_id=message.message_id,
        )
        await message.reply_text("✅ تم إرسال ردك إلى المستخدم.")
    except Exception:
        logger.exception("فشل إرسال رد المالك")
        await message.reply_text("❌ تعذر إرسال الرد.")

    return True


async def handle_user_message(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):
    message = update.effective_message
    user = update.effective_user

    if not message or not user:
        return

    await register_user(user)

    if is_owner(user.id):
        if await handle_owner_broadcast(update, context):
            return
        if await handle_owner_reply(update, context):
            return

        if OWNER_STATES.get(user.id) == "broadcast":
            return

        if message.text and message.text.strip() == "/start":
            await start(update, context)
            return

        return

    if message.text == "❌ إلغاء المراسلة":
        USER_STATES.pop(user.id, None)
        await message.reply_text(
            "تم إلغاء المراسلة.",
            reply_markup=main_keyboard(),
        )
        return

    if message.text == "🎬 تحميل من يوتيوب":
        USER_STATES.pop(user.id, None)
        await message.reply_text(
            "أرسل رابط فيديو يوتيوب.",
            reply_markup=main_keyboard(),
        )
        USER_STATES[user.id] = "waiting_url"
        return

    if message.text == "👨‍💻 مراسلة المالك":
        await handle_user_contact(update, context)
        return

    if USER_STATES.get(user.id) == "contact_owner":
        if OWNER_ID == 0:
            await message.reply_text(
                "المراسلة غير متاحة حاليًا."
            )
            return

        try:
            sent = await context.bot.copy_message(
                chat_id=OWNER_ID,
                from_chat_id=message.chat_id,
                message_id=message.message_id,
            )

            # ربط الرسالة الأصلية برسالة المالك
            DB["message_map"][str(sent.message_id)] = user.id
            await save_db()

            await message.reply_text(
                "✅ وصلت رسالتك إلى المالك. يمكنك إرسال رسالة أخرى."
            )
        except Exception:
            logger.exception("فشل تحويل رسالة المستخدم")
            await message.reply_text("❌ تعذر إرسال الرسالة.")

        return

    if message.text:
        url = message.text.strip()

        if not re.search(r"(youtube\.com/|youtu\.be/)", url):
            await message.reply_text(
                "أرسل رابط يوتيوب صحيحًا أو اختر أحد الأزرار."
            )
            return

        USER_STATES.pop(user.id, None)
        context.user_data["youtube_url"] = url

        await message.reply_text(
            "اختر الجودة أو صيغة الصوت:",
            reply_markup=video_keyboard(),
        )
        return


async def download_callback(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):
    query = update.callback_query
    await query.answer()

    url = context.user_data.get("youtube_url")

    if not url:
        await query.message.reply_text(
            "أرسل رابط يوتيوب أولًا."
        )
        return

    choice = query.data
    status = await query.message.reply_text(
        "⏳ جارٍ تجهيز الملف. قد يستغرق ذلك بعض الوقت..."
    )

    temp_dir = tempfile.mkdtemp(prefix="ytbot_")

    try:
        if choice == "audio_mp3":
            options = {
                "format": "bestaudio/best",
                "outtmpl": os.path.join(temp_dir, "%(id)s.%(ext)s"),
                "noplaylist": True,
                "quiet": True,
                "postprocessors": [{
                    "key": "FFmpegExtractAudio",
                    "preferredcodec": "mp3",
                    "preferredquality": "192",
                }],
            }
        else:
            quality = choice.split("_")[1]

            options = {
                "format": (
                    f"best[height<={quality}][ext=mp4]/"
                    f"best[height<={quality}]/best"
                ),
                "outtmpl": os.path.join(temp_dir, "%(id)s.%(ext)s"),
                "noplaylist": True,
                "quiet": True,
            }

        def run_download():
            with yt_dlp.YoutubeDL(options) as ydl:
                info = ydl.extract_info(url, download=True)
                path = Path(ydl.prepare_filename(info))

                if choice == "audio_mp3":
                    path = path.with_suffix(".mp3")

                return path, info.get("title", "video")

        path, title = await asyncio.to_thread(run_download)

        if not path.exists():
            await status.edit_text(
                "❌ لم يتم العثور على الملف بعد التحميل."
            )
            return

        size = path.stat().st_size

        if size > 49 * 1024 * 1024:
            await status.edit_text(
                "❌ الملف أكبر من حد الإرسال المحدد في هذا البوت."
            )
            return

        await status.edit_text(
            "✅ اكتمل التحميل، جارٍ إرسال الملف..."
        )

        with path.open("rb") as file_obj:
            if choice == "audio_mp3":
                await query.message.reply_audio(
                    audio=file_obj,
                    filename=path.name,
                    title=title[:64],
                    read_timeout=180,
                    write_timeout=180,
                )
            else:
                await query.message.reply_document(
                    document=file_obj,
                    filename=path.name,
                    read_timeout=180,
                    write_timeout=180,
                )

        await status.delete()

    except Exception:
        logger.exception("Download error")
        await status.edit_text(
            "❌ فشل التحميل.\n"
            "قد يكون الفيديو غير متاح أو يتطلب تحديث yt-dlp، "
            "أو أن الاستضافة لا تحتوي على FFmpeg."
        )

    finally:
        import shutil
        shutil.rmtree(temp_dir, ignore_errors=True)


async def error_handler(
    update: object,
    context: ContextTypes.DEFAULT_TYPE,
):
    logger.error(
        "حدث خطأ أثناء معالجة تحديث",
        exc_info=context.error,
    )


def main():
    if not TOKEN:
        raise RuntimeError(
            "يجب إضافة BOT_TOKEN في إعدادات الاستضافة."
        )

    if OWNER_ID == 0:
        raise RuntimeError(
            "يجب إضافة OWNER_ID، وهو رقم حساب المالك في تيليجرام."
        )

    app = Application.builder().token(TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("admin", admin_command))

    app.add_handler(
        CallbackQueryHandler(
            admin_callback,
            pattern=r"^admin_",
        )
    )

    app.add_handler(
        CallbackQueryHandler(
            download_callback,
            pattern=r"^(video_(360|480|720|1080)|audio_mp3)$",
        )
    )

    app.add_handler(
        MessageHandler(
            filters.ALL & ~filters.COMMAND,
            handle_user_message,
        )
    )

    app.add_error_handler(error_handler)

    logger.info("Bot is starting...")
    app.run_polling()


if __name__ == "__main__":
    main()
