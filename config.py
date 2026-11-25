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
