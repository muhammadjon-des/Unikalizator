import os
from dotenv import load_dotenv

load_dotenv()

BOT_TOKEN = os.environ["BOT_TOKEN"]
# Faqat shu Telegram ID'lar foydalana oladi (vergul bilan). Bo'sh bo'lsa — hamma.
ADMIN_IDS = {int(x) for x in os.getenv("ADMIN_IDS", "").split(",") if x.strip()}
# Yoki username bilan (vergul bilan, @ siz ham bo'ladi)
ADMIN_USERNAMES = {
    x.strip().lstrip("@").lower() for x in os.getenv("ADMIN_USERNAMES", "").split(",") if x.strip()
}

# 20 MB dan katta videolar uchun local Bot API server (ixtiyoriy)
TELEGRAM_API_SERVER = os.getenv("TELEGRAM_API_SERVER", "")

WORK_DIR = os.getenv("WORK_DIR", "./work")

# Instagram (ixtiyoriy). Bo'lsa — nusxalarni Trial Reels'ga ham joylash mumkin
IG_USER_ID = os.getenv("IG_USER_ID", "")
IG_ACCESS_TOKEN = os.getenv("IG_ACCESS_TOKEN", "")
IG_API_VERSION = os.getenv("IG_API_VERSION", "v24.0")
# MANUAL — followerlarga o'zingiz chiqarasiz; SS_PERFORMANCE — Instagram o'zi chiqaradi
TRIAL_STRATEGY = os.getenv("TRIAL_STRATEGY", "MANUAL")

# Instagram video_url uchun ochiq domen (Railway o'zi beradi) va port
PUBLIC_DOMAIN = os.getenv("PUBLIC_DOMAIN") or os.getenv("RAILWAY_PUBLIC_DOMAIN", "")
PORT = int(os.getenv("PORT", "8080"))

# YouTube -> Reels kliplar
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-flash-latest")
# Asosiy model band bo'lsa — shular sinab ko'riladi
GEMINI_FALLBACK = [m.strip() for m in os.getenv(
    "GEMINI_FALLBACK", "gemini-flash-lite-latest,gemini-pro-latest").split(",") if m.strip()]
YT_COOKIES = os.getenv("YT_COOKIES", "")  # cookies.txt matni (YouTube bloklasa)
CLIPS_MAX = int(os.getenv("CLIPS_MAX", "5"))

# Doimiy disk (Railway volume) — "men" rasmlari shu yerda saqlanadi
DATA_DIR = os.getenv("DATA_DIR", "/data")
UPLOAD_SECRET = os.getenv("UPLOAD_SECRET", "")  # /me-upload uchun maxfiy kalit
GEMINI_CHUNK_SEC = int(os.getenv("GEMINI_CHUNK_SEC", "900"))     # 15 daqiqalik bo'laklar
GEMINI_CHUNK_PAUSE = int(os.getenv("GEMINI_CHUNK_PAUSE", "30"))  # bo'laklar orasida kutish (s)
