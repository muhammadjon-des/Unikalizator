import asyncio
import logging
import shutil
import uuid
from pathlib import Path

from aiogram import Bot, Dispatcher, F, Router
from aiogram.client.session.aiohttp import AiohttpSession
from aiogram.client.telegram import TelegramAPIServer
from aiogram.exceptions import TelegramRetryAfter
from aiogram.filters import CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import (
    CallbackQuery, FSInputFile, InlineKeyboardButton, InlineKeyboardMarkup, Message,
)

import config
from uniquifier import make_variants

logging.basicConfig(level=logging.INFO)
router = Router()
WORK = Path(config.WORK_DIR)
job_lock = asyncio.Lock()  # bir vaqtda bitta video — server yuklanib ketmasin

MB = 1024 * 1024
DOWNLOAD_LIMIT = 2000 * MB if config.TELEGRAM_API_SERVER else 20 * MB
UPLOAD_LIMIT = 2000 * MB if config.TELEGRAM_API_SERVER else 50 * MB


class Flow(StatesGroup):
    count = State()
    mode = State()


def kb(rows):
    return InlineKeyboardMarkup(
        inline_keyboard=[[InlineKeyboardButton(text=t, callback_data=d) for t, d in row] for row in rows]
    )


def allowed(user) -> bool:
    if not config.ADMIN_IDS and not config.ADMIN_USERNAMES:
        return True
    return user.id in config.ADMIN_IDS or (user.username or "").lower() in config.ADMIN_USERNAMES


@router.message(CommandStart())
async def start(m: Message):
    if not allowed(m.from_user):
        return await m.answer("⛔ Ruxsat yo'q.")
    await m.answer(
        "🎬 <b>Unikalizator</b>\n\n"
        "Video yuboring — 3-5 ta unikal nusxasini qaytaraman.\n"
        "💡 Sifat buzilmasligi uchun videoni <b>fayl</b> qilib yuboring.",
        parse_mode="HTML",
    )


@router.message(F.video | F.document)
async def got_video(m: Message, state: FSMContext):
    if not allowed(m.from_user):
        return
    media = m.video or m.document
    if m.document and not (m.document.mime_type or "").startswith("video"):
        return await m.answer("Bu video emas.")
    if media.file_size and media.file_size > DOWNLOAD_LIMIT:
        return await m.answer(
            f"⚠️ Video {media.file_size // MB} MB. Bot {DOWNLOAD_LIMIT // MB} MB gacha qabul qiladi.\n"
            "Kattaroq videolar uchun local Bot API server kerak (README'da yozilgan)."
        )
    await state.set_data({"file_id": media.file_id})
    await state.set_state(Flow.count)
    await m.reply("Nechta nusxa?", reply_markup=kb([[("3", "c:3"), ("4", "c:4"), ("5", "c:5")]]))


@router.callback_query(Flow.count, F.data.startswith("c:"))
async def set_count(c: CallbackQuery, state: FSMContext):
    await state.update_data(count=int(c.data[2:]))
    await state.set_state(Flow.mode)
    await c.message.edit_text(
        "Rejimni tanlang:\n\n"
        "🔒 <b>Lossless</b> — kadrlar 100% o'zgarmaydi, faqat metadata va fayl xeshi yangi.\n\n"
        "✨ <b>Light</b> — ko'zga sezilmaydigan o'zgarishlar (crop 1-2%, rang, tezlik ±1.5%), "
        "deyarli yo'qotishsiz kodlash. Platformalar nusxani tanib qolishi ancha qiyin.",
        parse_mode="HTML",
        reply_markup=kb([[("🔒 Lossless", "m:lossless"), ("✨ Light", "m:light")]]),
    )


@router.callback_query(Flow.mode, F.data.startswith("m:"))
async def set_mode(c: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    data["mode"] = c.data[2:]
    await state.clear()
    await c.message.edit_text("⏳ Boshladim...")
    await c.answer()
    asyncio.create_task(process(c.message, c.bot, data))


async def process(status: Message, bot: Bot, data: dict):
    job_dir = WORK / uuid.uuid4().hex
    job_dir.mkdir(parents=True, exist_ok=True)

    async def say(t):
        try:
            await status.edit_text(t)
        except Exception:
            pass

    try:
        if job_lock.locked():
            await say("⏳ Navbatda (oldingi video ishlanyapti)...")
        async with job_lock:
            await say("⬇️ Video yuklab olinmoqda...")
            src = job_dir / "source.mp4"
            await bot.download(data["file_id"], destination=src)

            await say(f"⚙️ {data['count']} ta nusxa tayyorlanmoqda ({data['mode']})...")
            variants = await make_variants(src, data["count"], data["mode"], job_dir)

            for i, v in enumerate(variants, 1):
                await say(f"📤 {i}/{len(variants)} yuborilmoqda...")
                if v.stat().st_size > UPLOAD_LIMIT:
                    await status.answer(f"❌ {i}-nusxa {v.stat().st_size // MB} MB — Telegram limitidan katta.")
                    continue
                # Fayl sifatida — Telegram hech narsani siqmaydi
                await status.answer_document(
                    FSInputFile(v, filename=f"video_{i}.mp4"),
                    caption=f"#{i}",
                )
            await say(f"✅ Tayyor: {len(variants)} ta unikal nusxa.")
    except Exception as e:
        logging.exception("job failed")
        await say(f"❌ Xato: {e}")
    finally:
        shutil.rmtree(job_dir, ignore_errors=True)


async def main():
    session = None
    if config.TELEGRAM_API_SERVER:
        session = AiohttpSession(api=TelegramAPIServer.from_base(config.TELEGRAM_API_SERVER, is_local=True))
    bot = Bot(config.BOT_TOKEN, session=session)
    dp = Dispatcher()
    dp.include_router(router)
    # Flood control bo'lsa — qulamasdan kutib, qayta urinadi
    while True:
        try:
            me = await bot.get_me()
            info = await bot.get_webhook_info()
            logging.info("Bot: @%s | webhook: %r", me.username, info.url)
            await dp.start_polling(bot)
            break
        except TelegramRetryAfter as e:
            logging.warning("Flood control: %s s kutilmoqda", e.retry_after)
            await asyncio.sleep(e.retry_after + 2)
        except Exception:
            logging.exception("Polling xatosi, 10 s dan keyin qayta")
            await asyncio.sleep(10)


if __name__ == "__main__":
    asyncio.run(main())
