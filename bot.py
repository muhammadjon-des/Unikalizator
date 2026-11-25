import asyncio
import logging
import shutil
import uuid
from pathlib import Path

from aiogram import Bot, Dispatcher, F, Router
from aiogram.client.session.aiohttp import AiohttpSession
from aiogram.client.telegram import TelegramAPIServer
from aiogram.exceptions import TelegramRetryAfter
from aiogram.filters import Command, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import (
    CallbackQuery, FSInputFile, InlineKeyboardButton, InlineKeyboardMarkup, Message,
)

import config
from instagram import InstagramClient, InstagramError
import clipper
from uniquifier import make_variants

logging.basicConfig(level=logging.INFO)
router = Router()
WORK = Path(config.WORK_DIR)
# Instagram videoni ochiq URL'dan yuklab olishi uchun vaqtinchalik fayllar
PUBLIC_FILES: dict[str, Path] = {}
PUBLIC_BASE = (
    f"https://{config.PUBLIC_DOMAIN}" if config.PUBLIC_DOMAIN else ""
)


async def serve_file(request):
    from aiohttp import web
    path = PUBLIC_FILES.get(request.match_info["name"])
    if not path or not path.exists():
        raise web.HTTPNotFound()
    return web.FileResponse(path, headers={"Content-Type": "video/mp4"})


async def upload_me(request):
    """Egasining rasmini diskka yuklash (faqat UPLOAD_SECRET bilan)."""
    from aiohttp import web
    import hmac
    secret = config.UPLOAD_SECRET
    if not secret or not hmac.compare_digest(request.headers.get("X-Secret", ""), secret):
        raise web.HTTPForbidden()
    data = await request.read()
    if not data or len(data) > 5 * 1024 * 1024:
        raise web.HTTPBadRequest()
    clipper.ME_DIR.mkdir(parents=True, exist_ok=True)
    dst = clipper.ME_DIR / f"{uuid.uuid4().hex[:8]}.jpg"
    dst.write_bytes(data)
    return web.json_response({"ok": True, "total": len(clipper.me_photos())})


async def start_file_server():
    from aiohttp import web
    app = web.Application()
    app.router.add_get("/f/{name}", serve_file)
    app.router.add_get("/", lambda r: web.Response(text="ok"))
    app.router.add_post("/me-upload", upload_me)
    runner = web.AppRunner(app)
    await runner.setup()
    await web.TCPSite(runner, "0.0.0.0", config.PORT).start()
    logging.info("Fayl server: %s (port %s)", PUBLIC_BASE or "-", config.PORT)


job_lock = asyncio.Lock()  # bir vaqtda bitta video — server yuklanib ketmasin
ig = InstagramClient(config.IG_USER_ID, config.IG_ACCESS_TOKEN) if config.IG_ACCESS_TOKEN and config.IG_USER_ID else None

MB = 1024 * 1024
DOWNLOAD_LIMIT = 2000 * MB if config.TELEGRAM_API_SERVER else 20 * MB
UPLOAD_LIMIT = 2000 * MB if config.TELEGRAM_API_SERVER else 50 * MB


class Flow(StatesGroup):
    count = State()
    mode = State()
    dest = State()
    caption = State()


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
        "🎙 YouTube link yuboring — undan siz gapirgan eng zo'r joylarni Reels qilib kesaman.\n"
        "💡 Sifat buzilmasligi uchun videoni <b>fayl</b> qilib yuboring.",
        parse_mode="HTML",
    )
    if ig:
        try:
            acc = await ig.account()
            await m.answer(f"✅ Instagram ulangan: @{acc.get('username')}\n/limit — kunlik joylash limiti")
        except InstagramError as e:
            await m.answer(f"⚠️ Instagram ulanmadi: {e}")


@router.message(Command("limit"))
async def limit(m: Message):
    if not allowed(m.from_user) or not ig:
        return
    try:
        d = (await ig.publishing_limit())["data"][0]
        total = d.get("config", {}).get("quota_total", "?")
        await m.answer(f"24 soatda joylangan: {d.get('quota_usage')} / {total}")
    except Exception as e:
        await m.answer(f"Xato: {e}")


@router.message(Command("men"))
async def me_help(m: Message):
    if not allowed(m.from_user):
        return
    n = len(clipper.me_photos())
    await m.answer(
        f"📸 Saqlangan rasmlaringiz: {n}\n\n"
        "Yuzingiz aniq ko'rinadigan rasmni <b>«men»</b> izohi bilan yuboring — "
        "YouTube videolarda sizni o'zim taniyman. 1-3 ta turli rasm yaxshiroq.\n"
        "/men_tozala — rasmlarni o'chirish",
        parse_mode="HTML",
    )


@router.message(Command("men_tozala"))
async def me_clear(m: Message):
    if not allowed(m.from_user):
        return
    for p in clipper.user_photos():
        p.unlink(missing_ok=True)
    await m.answer("🗑 Rasmlar o'chirildi.")


@router.message(F.photo, F.caption.lower().in_({"men", "/men", "bu men"}))
async def me_photo(m: Message):
    if not allowed(m.from_user):
        return
    clipper.ME_DIR.mkdir(parents=True, exist_ok=True)
    photos = clipper.user_photos()
    if len(photos) >= 3:
        photos[0].unlink(missing_ok=True)  # eng eskisini almashtiramiz
    dst = clipper.ME_DIR / f"{uuid.uuid4().hex[:8]}.jpg"
    f = await m.bot.get_file(m.photo[-1].file_id)
    if config.TELEGRAM_API_SERVER:
        shutil.copy(f.file_path, dst)
    else:
        await m.bot.download(m.photo[-1].file_id, destination=dst)
    await m.answer(f"✅ Saqlandi (jami {len(clipper.me_photos())} ta). Endi YouTube videolarda sizni o'zim taniyman.")


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
    await state.set_data({"file_id": media.file_id, "orig_caption": m.caption or ""})
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
    await state.update_data(mode=c.data[2:])
    await c.answer()
    if not ig:
        return await start_job(c.message, c.bot, state, dest="tg")
    await state.set_state(Flow.dest)
    await c.message.edit_text(
        "Nusxalarni qayerga?",
        reply_markup=kb([
            [("📩 Telegram'ga", "d:tg")],
            [("🧪 Instagram Trial Reels", "d:ig")],
            [("Ikkalasiga", "d:both")],
        ]),
    )


@router.callback_query(Flow.dest, F.data.startswith("d:"))
async def set_dest(c: CallbackQuery, state: FSMContext):
    dest = c.data[2:]
    await c.answer()
    if dest == "tg":
        return await start_job(c.message, c.bot, state, dest=dest)
    await state.update_data(dest=dest)
    await state.set_state(Flow.caption)
    data = await state.get_data()
    rows = [[("Captionsiz", "cap:none")]]
    if data.get("orig_caption"):
        rows.insert(0, [("Video captionini ishlatish", "cap:orig")])
    await c.message.edit_text("Instagram uchun caption yozib yuboring yoki tanlang:", reply_markup=kb(rows))


@router.callback_query(Flow.caption, F.data.startswith("cap:"))
async def caption_btn(c: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    await c.answer()
    caption = data.get("orig_caption", "") if c.data == "cap:orig" else ""
    await start_job(c.message, c.bot, state, dest=data["dest"], caption=caption)


@router.message(Flow.caption, F.text)
async def caption_text(m: Message, state: FSMContext):
    data = await state.get_data()
    msg = await m.answer("⏳")
    await start_job(msg, m.bot, state, dest=data["dest"], caption=m.text)


async def start_job(msg: Message, bot: Bot, state: FSMContext, dest: str, caption: str = ""):
    data = await state.get_data()
    await state.clear()
    data.update(dest=dest, caption=caption)
    try:
        await msg.edit_text("⏳ Boshladim...")
    except Exception:
        pass
    asyncio.create_task(process(msg, bot, data))


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
            if config.TELEGRAM_API_SERVER:
                # Local server faylni o'z diskiga saqlaydi — ko'chirib olamiz (disk to'lmasin)
                f = await bot.get_file(data["file_id"])
                shutil.move(f.file_path, src)
            else:
                await bot.download(data["file_id"], destination=src)

            await say(f"⚙️ {data['count']} ta nusxa tayyorlanmoqda ({data['mode']})...")
            variants = await make_variants(src, data["count"], data["mode"], job_dir)

            dest = data.get("dest", "tg")
            if dest in ("tg", "both"):
                for i, v in enumerate(variants, 1):
                    await say(f"📤 Telegram: {i}/{len(variants)} yuborilmoqda...")
                    if v.stat().st_size > UPLOAD_LIMIT:
                        await status.answer(f"❌ {i}-nusxa {v.stat().st_size // MB} MB — Telegram limitidan katta.")
                        continue
                    # Fayl sifatida — Telegram hech narsani siqmaydi
                    await status.answer_document(
                        FSInputFile(v, filename=f"video_{i}.mp4"),
                        caption=f"#{i}",
                    )

            lines = []
            if dest in ("ig", "both") and ig:
                for i, v in enumerate(variants, 1):
                    await say("\n".join(lines + [f"🧪 Instagram: {i}/{len(variants)} yuklanmoqda..."]))
                    if not PUBLIC_BASE:
                        lines.append(f"❌ {i}: PUBLIC_DOMAIN sozlanmagan")
                        continue
                    name = f"{uuid.uuid4().hex}.mp4"
                    PUBLIC_FILES[name] = v
                    try:
                        media_id = await ig.post_trial_reel(
                            v, data.get("caption", ""), config.TRIAL_STRATEGY, f"{PUBLIC_BASE}/f/{name}"
                        )
                        lines.append(f"✅ {i}: {await ig.permalink(media_id) or media_id}")
                    except InstagramError as e:
                        lines.append(f"❌ {i}: {e}")
                        low = str(e).lower()
                        if "maximum" in low or "максимальн" in low:
                            lines.append("⛔ Trial Reels limiti tugadi — qolganlari joylanmadi. Keyinroq urinib ko'ring.")
                            PUBLIC_FILES.pop(name, None)
                            break
                    finally:
                        PUBLIC_FILES.pop(name, None)
                    await asyncio.sleep(5)

            done = f"✅ Tayyor: {len(variants)} ta unikal nusxa."
            if lines:
                ok = sum(l.startswith("✅") for l in lines)
                done += f"\nTrial Reels: {ok}/{len(variants)} joylandi\n\n" + "\n".join(lines)
            await say(done)
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
    await start_file_server()
    # Flood control bo'lsa — qulamasdan, har safar uzoqroq kutib qayta urinadi
    backoff = 0
    while True:
        try:
            me = await bot.get_me()
            info = await bot.get_webhook_info()
            logging.info("Bot: @%s | webhook: %r", me.username, info.url)
            await dp.start_polling(bot)
            break
        except TelegramRetryAfter as e:
            wait = min(max(e.retry_after, 30) * (2 ** backoff), 900)
            backoff = min(backoff + 1, 5)
            logging.warning("Flood control (%s s). %s s kutilmoqda", e.retry_after, wait)
            await asyncio.sleep(wait)
        except Exception:
            logging.exception("Polling xatosi, 10 s dan keyin qayta")
            await asyncio.sleep(10)



# ---------------- YouTube -> Reels ----------------
# chat_id -> {"url", "speakers", "clips"}
YT_JOBS: dict[int, dict] = {}


@router.message(F.text.regexp(clipper.YOUTUBE_RE))
async def got_youtube(m: Message, state: FSMContext):
    if not allowed(m.from_user):
        return
    await state.clear()
    url = clipper.YOUTUBE_RE.search(m.text).group(0)
    if not url.startswith("http"):
        url = "https://" + url
    status = await m.answer("🧠 Video tahlil qilinmoqda (Gemini)... 1-5 daqiqa")
    try:
        res = await clipper.analyze(url)
    except clipper.ClipError as e:
        return await status.edit_text(f"❌ Tahlil xatosi: {e}")
    speakers = res.get("speakers") or []
    if not res["clips"]:
        return await status.edit_text("Mos bo'lak topilmadi 🤷")
    YT_JOBS[m.chat.id] = {"url": url, **res}
    if len(speakers) <= 1:
        sid = speakers[0]["id"] if speakers else res["clips"][0]["speaker"]
        return await cut_clips(status, m.bot, m.chat.id, sid)
    owner = res.get("owner")
    if owner and any(c.get("speaker") == owner for c in res["clips"]):
        await status.edit_text("🙂 Sizni rasmingizdan tanidim. Kliplar kesilmoqda...")
        return await cut_clips(status, m.bot, m.chat.id, owner)
    rows = [[(f"{sp['id']}: {sp.get('desc', '')}"[:60], f"sp:{sp['id']}")] for sp in speakers]
    await status.edit_text("Videoda bir nechta odam bor. Qaysi biri siz?", reply_markup=kb(rows))


@router.callback_query(F.data.startswith("sp:"))
async def pick_speaker(c: CallbackQuery):
    await c.answer()
    await cut_clips(c.message, c.bot, c.message.chat.id, c.data[3:])


async def cut_clips(status: Message, bot: Bot, chat_id: int, speaker: str):
    job = YT_JOBS.pop(chat_id, None)
    if not job:
        return await status.edit_text("Eski so'rov. Linkni qayta yuboring.")
    clips = [c for c in job["clips"] if c.get("speaker") == speaker][: config.CLIPS_MAX]
    if not clips:
        return await status.edit_text("Bu odam uchun mos bo'lak topilmadi.")
    work = WORK / uuid.uuid4().hex
    work.mkdir(parents=True, exist_ok=True)

    async def say(t):
        try:
            await status.edit_text(t)
        except Exception:
            pass

    try:
        if job_lock.locked():
            await say("⏳ Navbatda (oldingi ish tugashini kutyapman)...")
        async with job_lock:
            ok = 0
            for i, clip in enumerate(clips, 1):
                await say(f"✂️ {i}/{len(clips)} klip kesilmoqda...")
                try:
                    out = await clipper.make_clip(job["url"], clip, work)
                except clipper.ClipError as e:
                    msg = str(e)
                    if "Sign in" in msg or "bot" in msg.lower():
                        msg = "YouTube bloklayapti — YT_COOKIES kerak (README)"
                    await status.answer(f"❌ {i}-klip: {msg[:300]}")
                    continue
                s, e = int(clip["start"]), int(clip["end"])
                await status.answer_video(
                    FSInputFile(out, filename=f"reel_{i}.mp4"),
                    caption=f"#{i} • {s // 60}:{s % 60:02d}–{e // 60}:{e % 60:02d}\n"
                            f"<b>{clip.get('hook', '')}</b>\n{clip.get('why', '')}",
                    parse_mode="HTML",
                    width=1080, height=1920, supports_streaming=True,
                )
                ok += 1
            await say(f"✅ Tayyor: {ok}/{len(clips)} ta reel.\n"
                      "Yoqqanini botga qayta yuborsangiz — unikal nusxa qilib Trial Reels'ga joylayman.")
    except Exception as e:
        logging.exception("clip job failed")
        await say(f"❌ Xato: {e}")
    finally:
        shutil.rmtree(work, ignore_errors=True)


@router.message(F.text)
async def fallback_text(m: Message):
    if not allowed(m.from_user):
        return
    logging.info("Tushunilmagan matn: %r", (m.text or "")[:200])
    await m.answer("Video fayl yoki YouTube link yuboring. /start — yordam")


if __name__ == "__main__":
    asyncio.run(main())
