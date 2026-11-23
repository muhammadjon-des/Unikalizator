"""
Videoning unikal nusxalarini yasash.

Ikki rejim:
  lossless — kadrlarga umuman tegmaydi (-c copy). Faqat metadata, konteyner
             va fayl xeshi o'zgaradi. Sifat 100% bir xil.
  light    — ko'zga ko'rinmaydigan o'zgarishlar (1-2% crop, rang ±1-2%,
             tezlik ±1-2%, juda past shovqin) + deyarli yo'qotishsiz
             kodlash (CRF 16). Sifat farqi ko'zga sezilmaydi.
"""
import asyncio
import json
import random
import string
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path


async def _run(*args: str) -> str:
    proc = await asyncio.create_subprocess_exec(
        *args, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
    )
    out, err = await proc.communicate()
    if proc.returncode != 0:
        raise RuntimeError(f"{args[0]} xato: {err.decode(errors='ignore')[-800:]}")
    return out.decode(errors="ignore")


async def probe(path: Path) -> dict:
    out = await _run(
        "ffprobe", "-v", "error", "-print_format", "json",
        "-show_streams", "-show_format", str(path),
    )
    data = json.loads(out)
    v = next(s for s in data["streams"] if s["codec_type"] == "video")
    has_audio = any(s["codec_type"] == "audio" for s in data["streams"])
    num, den = (v.get("r_frame_rate") or "30/1").split("/")
    return {
        "width": int(v["width"]),
        "height": int(v["height"]),
        "fps": float(num) / float(den or 1),
        "duration": float(data["format"].get("duration", 0)),
        "bitrate": int(data["format"].get("bit_rate", 0) or 0),
        "has_audio": has_audio,
    }


def _random_meta() -> list[str]:
    rnd = "".join(random.choices(string.ascii_letters + string.digits, k=12))
    t = datetime.now(timezone.utc) - timedelta(minutes=random.randint(5, 60 * 24 * 20))
    return [
        "-map_metadata", "-1",
        "-metadata", f"title={rnd}",
        "-metadata", f"comment={uuid.uuid4()}",
        "-metadata", f"creation_time={t.strftime('%Y-%m-%dT%H:%M:%S.000000Z')}",
        "-metadata", f"encoder={random.choice(['Lavf60.16.100', 'Lavf61.1.100', 'Lavf59.27.100'])}",
    ]


async def _make_lossless(src: Path, dst: Path) -> None:
    await _run(
        "ffmpeg", "-y", "-v", "error", "-i", str(src),
        "-map", "0:v:0", "-map", "0:a?",
        "-c", "copy",
        *_random_meta(),
        "-movflags", "+faststart",
        str(dst),
    )


async def _make_light(src: Path, dst: Path, info: dict) -> None:
    w, h = info["width"], info["height"]
    # 1-2% crop va asl o'lchamga qaytarish
    c = random.uniform(0.01, 0.02)
    cw, ch = int(w * (1 - c)) // 2 * 2, int(h * (1 - c)) // 2 * 2
    cx = random.randint(0, w - cw)
    cy = random.randint(0, h - ch)
    speed = random.uniform(0.985, 1.015)
    bright = random.uniform(-0.015, 0.015)
    contrast = random.uniform(0.985, 1.015)
    sat = random.uniform(0.98, 1.03)
    gamma = random.uniform(0.98, 1.02)
    noise = random.randint(1, 3)

    vf = (
        f"crop={cw}:{ch}:{cx}:{cy},"
        f"scale={w}:{h}:flags=lanczos,"
        f"eq=brightness={bright:.4f}:contrast={contrast:.4f}:saturation={sat:.4f}:gamma={gamma:.4f},"
        f"noise=alls={noise}:allf=t,"
        f"setpts=PTS/{speed:.4f},"
        f"format=yuv420p"
    )
    # asl bitreytdan past bo'lmasin
    maxrate = max(info["bitrate"] * 2, 12_000_000)

    args = [
        "ffmpeg", "-y", "-v", "error", "-i", str(src),
        "-vf", vf,
        "-c:v", "libx264", "-preset", "slow", "-crf", "16",
        "-maxrate", str(maxrate), "-bufsize", str(maxrate * 2),
        "-profile:v", "high", "-pix_fmt", "yuv420p",
    ]
    if info["has_audio"]:
        vol = random.uniform(0.97, 1.03)
        args += [
            "-af", f"atempo={speed:.4f},volume={vol:.3f}",
            "-c:a", "aac", "-b:a", "256k", "-ar", "48000",
        ]
    else:
        args += ["-an"]
    args += [*_random_meta(), "-movflags", "+faststart", str(dst)]
    await _run(*args)


async def make_variants(src: Path, count: int, mode: str, out_dir: Path) -> list[Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    info = await probe(src)
    result = []
    for i in range(count):
        dst = out_dir / f"v{i + 1}_{uuid.uuid4().hex[:8]}.mp4"
        if mode == "lossless":
            await _make_lossless(src, dst)
        else:
            await _make_light(src, dst, info)
        result.append(dst)
    return result
