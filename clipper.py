"""
YouTube podkastdan Reels kliplar yasash.

1. Gemini YouTube URL'ni ko'radi: spikerlarni ajratadi, har biri uchun eng yaxshi
   25-60 soniyalik bo'laklarni, hook matnini va yuz joylashuvini (x) qaytaradi.
2. yt-dlp faqat kerakli bo'lakni yuklaydi (butun videoni emas).
3. ffmpeg: 16:9 -> 9:16, kadr spiker yuziga qarab siljiydi, tepada hook yozuvi.
"""
import asyncio
import json
import re
import textwrap
import uuid
from pathlib import Path

import httpx

import config

YOUTUBE_RE = re.compile(
    r"(https?://)?(www\.|m\.)?(youtube\.com/(watch\?v=|shorts/|live/)|youtu\.be/)[\w\-]{6,}[^\s]*"
)
FONT = next(
    (f for f in (
        "/usr/share/fonts/dejavu/DejaVuSans-Bold.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        "/usr/share/fonts/TTF/DejaVuSans-Bold.ttf",
    ) if Path(f).exists()),
    "/usr/share/fonts/dejavu/DejaVuSans-Bold.ttf",
)

PROMPT = """You are an expert short-form video editor. The video is a podcast / interview in Uzbek (may contain Russian).

Task:
1. Identify every distinct on-camera speaker. For each give:
   - "id": "S1", "S2", ...
   - "desc": short VISUAL description in Uzbek Latin (clothes, hair, glasses, which side of frame) so the owner can recognise himself. Max 10 words.
2. For EACH speaker, find the best self-contained moments for Instagram Reels where THAT speaker talks:
   - 25 to 60 seconds long, complete thought, starts at the beginning of a sentence and ends at the end of a sentence
   - the first sentence must be a strong hook (surprising claim, money, mistake, story, controversial opinion, useful tip)
   - avoid greetings, intros, sponsor reads, cross-talk
   - up to 6 clips per speaker, best first
   For each clip return:
   - "speaker": speaker id
   - "start", "end": seconds from the start of the video (numbers, may have decimals)
   - "hook": on-screen title in Uzbek Latin, max 7 words, catchy, no emojis, no quotes
   - "why": one short sentence in Uzbek why this will perform
   - "shots": list of {"t": seconds from video start, "x": 0..1 horizontal centre of THIS speaker's face in the frame}. First entry at clip start, add a new entry at every camera cut / reframing inside the clip. If the speaker is not visible in a shot, use the x of whoever is on screen.

Return ONLY JSON:
{"speakers":[{"id":"S1","desc":"..."}],"clips":[{"speaker":"S1","start":0,"end":0,"hook":"...","why":"...","shots":[{"t":0,"x":0.5}]}]}
"""


ME_PROMPT = """
REFERENCE PHOTOS: the image(s) before the video show the channel OWNER (same face; clothes and hair may differ).
Decide which speaker in the video is the owner by comparing faces. Add "owner": "<speaker id>" to the top-level JSON
(or "owner": null if the owner does not appear). You may then return clips ONLY for the owner.
"""

ME_DIR = Path(config.DATA_DIR) / "me"


REPO_ME_DIR = Path(__file__).parent / "me"  # repoda turgan egasining rasmlari


def me_photos() -> list[Path]:
    """Diskdagi (bot orqali yuborilgan) + repodagi rasmlar, ko'pi bilan 8 ta."""
    out = []
    for d in (ME_DIR, REPO_ME_DIR):
        if d.exists():
            out += sorted(d.glob("*.jpg"))
    return out[:8]


def user_photos() -> list[Path]:
    """Faqat bot orqali yuborilganlar (o'chirish/limit uchun)."""
    return sorted(ME_DIR.glob("*.jpg")) if ME_DIR.exists() else []


class ClipError(Exception):
    pass


async def _run(*args: str, timeout: int = 1800) -> str:
    proc = await asyncio.create_subprocess_exec(
        *args, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
    )
    try:
        out, err = await asyncio.wait_for(proc.communicate(), timeout)
    except asyncio.TimeoutError:
        proc.kill()
        raise ClipError(f"{args[0]} juda uzoq ishladi")
    if proc.returncode != 0:
        raise ClipError(f"{args[0]}: {err.decode(errors='ignore')[-600:]}")
    return out.decode(errors="ignore")


def _parse_json(text: str) -> dict:
    text = text.strip()
    if text.startswith("```"):
        text = text.strip("`").split("\n", 1)[1].rsplit("```", 1)[0]
    m = re.search(r"\{.*\}", text, re.S)
    if not m:
        raise ClipError("Gemini javobi JSON emas")
    return json.loads(m.group(0))


class QuotaError(ClipError):
    pass


async def _gemini(body: dict) -> dict:
    """Band bo'lsa qayta urinadi, daqiqalik limitda kutadi, zaxira modelga o'tadi."""
    models = [config.GEMINI_MODEL] + [m for m in config.GEMINI_FALLBACK if m != config.GEMINI_MODEL]
    last = "noma'lum xato"
    async with httpx.AsyncClient(timeout=httpx.Timeout(900, connect=30)) as http:
        for model in models:
            api = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
            quota_waits = 0
            attempt = 0
            while attempt < 3:
                r = await http.post(api, headers={"x-goog-api-key": config.GEMINI_API_KEY}, json=body)
                try:
                    data = r.json()
                except Exception:
                    data = {"error": {"message": f"HTTP {r.status_code}: {r.text[:200]}"}}
                if "error" not in data:
                    return data
                last = data["error"].get("message", str(data["error"]))
                low = last.lower()
                if r.status_code == 404:
                    break  # bunday model yo'q — keyingisiga
                if "quota" in low or "billing" in low or "resource_exhausted" in low:
                    # daqiqalik limit bo'lsa — 1 daqiqa kutish yetadi; kunlik bo'lsa — 2 urinishdan keyin to'xtaymiz
                    if quota_waits < 2:
                        quota_waits += 1
                        await asyncio.sleep(65)
                        continue
                    break  # bu modelda kvota tugadi — keyingi modelga
                busy = r.status_code in (500, 503) or "demand" in low or "overloaded" in low
                if not busy:
                    raise ClipError(f"Gemini ({model}): {last}")
                await asyncio.sleep(10 * (2 ** attempt))  # 10, 20, 40 s
                attempt += 1
    if "quota" in last.lower():
        raise QuotaError("Gemini bepul limiti tugadi. Bir necha soatdan keyin yoki ertaga urinib ko'ring.")
    raise ClipError(f"Gemini hozir band, keyinroq urinib ko'ring ({last[:150]})")


async def video_duration(url: str) -> float | None:
    """yt-dlp bilan davomiylik (yuklamasdan). Bloklansa — None."""
    try:
        out = await _run(
            "yt-dlp", "--no-playlist", "--skip-download", "--js-runtimes", "node",
            "--print", "duration", url, timeout=90,
        )
        return float(out.strip().splitlines()[-1])
    except Exception:
        return None


def _photo_parts() -> list[dict]:
    import base64
    return [
        {"inline_data": {"mime_type": "image/jpeg", "data": base64.b64encode(p.read_bytes()).decode()}}
        for p in me_photos()
    ]


async def _analyze_chunk(url: str, start: int | None, end: int | None) -> dict:
    video = {"file_data": {"file_uri": url, "mime_type": "video/*"}}
    note = ""
    if start is not None:
        video["video_metadata"] = {"start_offset": f"{start}s", "end_offset": f"{end}s"}
        note = (f"\nYou are seeing only the segment {start}s-{end}s of the full video. "
                "Return start/end/shots timestamps as ABSOLUTE seconds from the beginning of the FULL video.\n")
    photos = _photo_parts()
    body = {
        "contents": [{"parts": photos + [video, {"text": PROMPT + note + (ME_PROMPT if photos else "")}]}],
        "generationConfig": {
            "responseMimeType": "application/json",
            "mediaResolution": "MEDIA_RESOLUTION_LOW",
            "temperature": 0.4,
        },
    }
    data = await _gemini(body)
    try:
        text = "".join(p.get("text", "") for p in data["candidates"][0]["content"]["parts"])
    except (KeyError, IndexError):
        raise ClipError(f"Gemini bo'sh javob qaytardi: {str(data)[:300]}")
    res = _parse_json(text)
    clips = []
    for c in res.get("clips", []):
        try:
            s, e = float(c["start"]), float(c["end"])
        except (KeyError, TypeError, ValueError):
            continue
        # Model segmentga nisbatan vaqt bergan bo'lsa — to'g'rilaymiz
        if start and s < start - 5:
            s, e = s + start, e + start
            for sh in c.get("shots") or []:
                try:
                    sh["t"] = float(sh["t"]) + start
                except (KeyError, TypeError, ValueError):
                    pass
        if 8 <= e - s <= 120:
            c["start"], c["end"] = s, e
            clips.append(c)
    res["clips"] = clips
    return res


async def analyze(url: str, progress=None) -> dict:
    """Uzun videoni bo'laklarga bo'lib tahlil qiladi (bepul limitga sig'ishi uchun)."""
    if not config.GEMINI_API_KEY:
        raise ClipError("GEMINI_API_KEY sozlanmagan")
    chunk = config.GEMINI_CHUNK_SEC
    dur = await video_duration(url)
    if dur and dur <= chunk * 1.2:
        ranges = [(None, None)]
    else:
        n = int((dur or chunk * 12) // chunk) + 1
        ranges = [(i * chunk, (i + 1) * chunk) for i in range(n)]

    speakers: dict[str, dict] = {}   # desc -> speaker (bo'laklar bo'ylab birlashtirish)
    owner_clips, other_clips = [], []
    owner_seen = False
    for i, (a, b) in enumerate(ranges, 1):
        if progress and len(ranges) > 1:
            await progress(f"🧠 Tahlil: {i}/{len(ranges)}-qism ({a // 60}-{b // 60} daqiqa)...")
        try:
            res = await _analyze_chunk(url, a, b)
        except QuotaError:
            if owner_clips or other_clips:
                break  # bor natija bilan davom etamiz
            raise
        except ClipError:
            if dur is None and i > 1:
                break  # davomiylik noma'lum — video tugagan bo'lishi mumkin
            raise
        sp_desc = {sp.get("id"): sp.get("desc", sp.get("id")) for sp in res.get("speakers", [])}
        owner = res.get("owner")
        for c in res["clips"]:
            c["chunk"] = i
            if owner and c.get("speaker") == owner:
                c["speaker"] = "ME"
                owner_clips.append(c)
            else:
                d = sp_desc.get(c.get("speaker"), c.get("speaker", "?"))
                key = d.lower().strip()
                speakers.setdefault(key, {"id": f"P{len(speakers) + 1}", "desc": d})
                c["speaker"] = speakers[key]["id"]
                other_clips.append(c)
        owner_seen = owner_seen or bool(owner)
        if dur is None and not res["clips"] and i > 1:
            break
        if i < len(ranges):
            await asyncio.sleep(config.GEMINI_CHUNK_PAUSE)

    def spread(clips):
        # har bir qismdan navbat bilan — butun video bo'ylab eng yaxshilari
        by = {}
        for c in clips:
            by.setdefault(c["chunk"], []).append(c)
        out = []
        while any(by.values()):
            for k in sorted(by):
                if by[k]:
                    out.append(by[k].pop(0))
        return out

    if owner_clips:
        return {"owner": "ME", "speakers": [{"id": "ME", "desc": "Siz"}], "clips": spread(owner_clips)}
    return {"owner": None, "speakers": list(speakers.values()), "clips": spread(other_clips)}


def _cookies_file(work: Path) -> list[str]:
    if not config.YT_COOKIES:
        return []
    p = work / "cookies.txt"
    p.write_text(config.YT_COOKIES)
    return ["--cookies", str(p)]


async def download_section(url: str, start: float, end: float, work: Path) -> Path:
    out = work / f"raw_{uuid.uuid4().hex[:8]}.%(ext)s"
    await _run(
        "yt-dlp", "--no-playlist", "--quiet", "--no-warnings", "--js-runtimes", "node",
        *_cookies_file(work),
        "-f", "bv*[height<=1080]+ba/b[height<=1080]/b",
        "--download-sections", f"*{max(start, 0):.2f}-{end:.2f}",
        "--force-keyframes-at-cuts",
        "--merge-output-format", "mp4",
        "-o", str(out),
        url,
    )
    files = sorted(work.glob(out.name.replace("%(ext)s", "*")))
    if not files:
        raise ClipError("yt-dlp fayl yaratmadi")
    return files[0]


async def _size(path: Path) -> tuple[int, int, float]:
    out = await _run(
        "ffprobe", "-v", "error", "-select_streams", "v:0",
        "-show_entries", "stream=width,height:format=duration", "-of", "json", str(path),
    )
    d = json.loads(out)
    st = d["streams"][0]
    return int(st["width"]), int(st["height"]), float(d["format"].get("duration", 0))


def _wrap_hook(hook: str) -> str:
    hook = re.sub(r"\s+", " ", hook).strip().upper()
    return "\n".join(textwrap.wrap(hook, width=18)[:3])


async def render(raw: Path, clip: dict, clip_start: float, out: Path) -> Path:
    """9:16, kadr yuz bo'yicha, tepada hook."""
    w, h, _ = await _size(raw)
    filters = []
    if w / h > 9 / 16:
        cw = int(h * 9 / 16) // 2 * 2
        # shots -> crop x (piksel), vaqt klip boshidan
        shots = sorted(clip.get("shots") or [{"t": clip["start"], "x": 0.5}], key=lambda s: float(s.get("t", 0)))
        pts = []
        for s in shots:
            try:
                t = max(float(s["t"]) - clip_start, 0.0)
                x = min(max(float(s["x"]), 0.0), 1.0)
            except (KeyError, TypeError, ValueError):
                continue
            px = int(min(max(x * w - cw / 2, 0), w - cw))
            pts.append((t, px))
        if not pts:
            pts = [(0.0, (w - cw) // 2)]
        expr = str(pts[-1][1])
        for i in reversed(range(len(pts) - 1)):
            expr = f"if(lt(t\\,{pts[i + 1][0]:.2f})\\,{pts[i][1]}\\,{expr})"
        filters.append(f"crop={cw}:{h}:{expr}:0")
    filters.append("scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920,setsar=1")

    hook = _wrap_hook(clip.get("hook", ""))
    if hook:
        hook_file = out.with_suffix(".txt")
        hook_file.write_text(hook)
        filters.append(
            f"drawtext=fontfile={FONT}:textfile={hook_file}:fontsize=66:fontcolor=white"
            ":line_spacing=14:box=1:boxcolor=black@0.85:boxborderw=26"
            ":x=(w-text_w)/2:y=h*0.13"
        )
    await _run(
        "ffmpeg", "-y", "-v", "error", "-i", str(raw),
        "-vf", ",".join(filters),
        "-c:v", "libx264", "-preset", "veryfast", "-crf", "20", "-pix_fmt", "yuv420p",
        "-c:a", "aac", "-b:a", "192k", "-movflags", "+faststart",
        str(out),
    )
    return out


REFINE_PROMPT = """This is a {dur:.0f}-second segment cut from a long Uzbek podcast (may contain Russian).
{owner_note}
Tasks:
1. Inside this segment find the single best self-contained moment for Instagram Reels where {who} is speaking:
   20-60 seconds, starts exactly at the beginning of a sentence, ends exactly at the end of a sentence.
2. "hook": on-screen title in Uzbek Latin, max 7 words, that ACCURATELY reflects what is actually said in that moment
   (no invented facts), catchy, no emojis, no quotes.
3. "why": one short Uzbek sentence why it will perform.
4. "faces": for every second from start to end: {{"t": seconds from the segment start, "x": horizontal centre (0..1) of
   {who_face} face in the frame}}. Be precise: x is measured on the full frame width. If that person is not visible,
   use the face of whoever is on screen.
5. "owner_speaks": true/false — does {who} actually speak in the chosen moment.
Return ONLY JSON: {{"owner_speaks":true,"start":0,"end":0,"hook":"...","why":"...","faces":[{{"t":0,"x":0.5}}]}}
Times are seconds from the start of THIS segment."""


async def _proxy(src: Path, work: Path) -> Path:
    """Gemini uchun kichik nusxa (360p, past bitreyt) — inline yuborish uchun."""
    out = work / f"proxy_{uuid.uuid4().hex[:6]}.mp4"
    await _run(
        "ffmpeg", "-y", "-v", "error", "-i", str(src),
        "-vf", "scale=-2:360,fps=5", "-c:v", "libx264", "-preset", "veryfast", "-crf", "33",
        "-c:a", "aac", "-b:a", "48k", "-ac", "1", str(out),
    )
    return out


async def refine(raw: Path, work: Path) -> dict | None:
    """Kesilgan oynani Gemini'ga qayta ko'rsatib: aniq start/end, mos hook, yuz joylashuvi."""
    import base64
    _, _, dur = await _size(raw)
    proxy = await _proxy(raw, work)
    if proxy.stat().st_size > 18 * 1024 * 1024:
        return None
    photos = _photo_parts()
    if photos:
        owner_note = "The image(s) before the video show the channel OWNER."
        who, who_face = "the OWNER (from the reference photos)", "the OWNER's"
    else:
        owner_note, who, who_face = "", "the main speaker", "the speaking person's"
    body = {
        "contents": [{"parts": photos + [
            {"inline_data": {"mime_type": "video/mp4", "data": base64.b64encode(proxy.read_bytes()).decode()}},
            {"text": REFINE_PROMPT.format(dur=dur, owner_note=owner_note, who=who, who_face=who_face)},
        ]}],
        "generationConfig": {"responseMimeType": "application/json", "temperature": 0.3},
    }
    try:
        data = await _gemini(body)
        text = "".join(p.get("text", "") for p in data["candidates"][0]["content"]["parts"])
        r = _parse_json(text)
        r["start"], r["end"] = float(r["start"]), float(r["end"])
        if not (5 <= r["end"] - r["start"] <= 90) or r["start"] < 0 or r["end"] > dur + 1:
            return None
        return r
    except Exception as e:
        import logging
        logging.warning("refine failed: %s", e)
        return None


def _faces_to_shots(faces: list, offset: float) -> list:
    """Har soniyalik x -> shots: kichik tebranishlarni silliqlab, faqat katta sakrashda kadrni almashtiramiz."""
    pts = []
    for f in sorted(faces or [], key=lambda f: float(f.get("t", 0))):
        try:
            pts.append((float(f["t"]) + offset, min(max(float(f["x"]), 0.0), 1.0)))
        except (KeyError, TypeError, ValueError):
            continue
    if not pts:
        return []
    shots = [{"t": pts[0][0], "x": pts[0][1]}]
    group = [pts[0][1]]
    for t, x in pts[1:]:
        cur = sorted(group)[len(group) // 2]
        if abs(x - cur) > 0.12:           # kamera almashdi / boshqa kadr
            shots[-1]["x"] = cur
            shots.append({"t": t, "x": x})
            group = [x]
        else:
            group.append(x)
    shots[-1]["x"] = sorted(group)[len(group) // 2]
    return shots


async def _finish(raw: Path, win_start: float, clip: dict, work: Path) -> Path:
    """raw = keng oyna. Refine bo'lsa — uni ishlatamiz, bo'lmasa Gemini'ning birinchi taxmini."""
    r = await refine(raw, work)
    if r:
        if r.get("owner_speaks") is False and me_photos():
            raise ClipError("bu bo'lakda siz gapirmayapsiz — o'tkazib yuborildi")
        s_rel, e_rel = max(r["start"] - 0.2, 0), r["end"] + 0.3
        clip["start"], clip["end"] = win_start + s_rel, win_start + e_rel
        clip["hook"] = r.get("hook") or clip.get("hook", "")
        clip["why"] = r.get("why") or clip.get("why", "")
        shots = _faces_to_shots(r.get("faces"), win_start)
        if shots:
            clip["shots"] = shots
    else:
        s_rel = max(clip["start"] - 0.3 - win_start, 0)
        e_rel = clip["end"] + 0.4 - win_start
    seg = work / f"seg_{uuid.uuid4().hex[:6]}.mp4"
    await _run(
        "ffmpeg", "-y", "-v", "error", "-ss", f"{s_rel:.2f}", "-i", str(raw), "-t", f"{e_rel - s_rel:.2f}",
        "-c:v", "libx264", "-preset", "ultrafast", "-crf", "16", "-c:a", "aac", "-b:a", "192k", str(seg),
    )
    return await render(seg, clip, win_start + s_rel, work / f"reel_{uuid.uuid4().hex[:8]}.mp4")


PAD = 10.0  # aniqlashtirish uchun klip atrofidan qo'shimcha soniyalar


async def make_clip(url: str, clip: dict, work: Path) -> Path:
    win_start = max(clip["start"] - PAD, 0)
    raw = await download_section(url, win_start, clip["end"] + PAD, work)
    return await _finish(raw, win_start, clip, work)


def is_blocked(err: str) -> bool:
    e = err.lower()
    return "sign in" in e or "not a bot" in e or "429" in e or "cookies" in e


async def cut_from_file(src: Path, clip: dict, work: Path) -> Path:
    """YouTube o'rniga foydalanuvchi yuborgan asl fayldan kesish."""
    win_start = max(clip["start"] - PAD, 0)
    dur = clip["end"] + PAD - win_start
    raw = work / f"win_{uuid.uuid4().hex[:8]}.mp4"
    await _run(
        "ffmpeg", "-y", "-v", "error", "-ss", f"{win_start:.2f}", "-i", str(src), "-t", f"{dur:.2f}",
        "-c:v", "libx264", "-preset", "ultrafast", "-crf", "16", "-c:a", "aac", "-b:a", "192k",
        str(raw),
    )
    return await _finish(raw, win_start, clip, work)
