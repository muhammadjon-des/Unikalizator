# Unikalizator bot

Telegram'ga video tashlaysiz → bot 3-5 ta unikal nusxa yasab, fayl qilib qaytaradi.

## Rejimlar

- **🔒 Lossless** — kadrlar umuman o'zgarmaydi (`-c copy`). Faqat metadata (sana, nom, encoder) va fayl xeshi yangi. Sifat 100% bir xil.
- **✨ Light** — har bir nusxada tasodifiy: 1-2% crop, yorqinlik/kontrast/to'yinganlik ±1.5%, tezlik ±1.5%, ovoz balandligi ±3%, juda yengil shovqin. Kodlash CRF 16 (deyarli yo'qotishsiz) — ko'zga farq sezilmaydi.

Instagram/TikTok nusxani ko'rinishidan solishtiradi, shuning uchun haqiqiy unikallik uchun **Light** ishonchliroq.

## O'rnatish

1. @BotFather'da bot yarating → token oling.
2. O'z Telegram ID'ingizni @userinfobot'dan oling.
3. `.env.example` → `.env` qilib nusxalang va to'ldiring.

```bash
pip install -r requirements.txt   # ffmpeg ham o'rnatilgan bo'lishi kerak
python bot.py
```

Docker:
```bash
docker build -t unikalizator .
docker run -d --env-file .env --restart always unikalizator
```

Railway: repo'ni ulang — `Dockerfile` avtomatik ishlatiladi. Variables'ga `BOT_TOKEN` va `ADMIN_IDS` qo'shing.

## Fayl hajmi cheklovlari

Oddiy Telegram Bot API: **20 MB** gacha qabul qiladi, **50 MB** gacha yuboradi.
Railway variant: `TELEGRAM_API_ID` va `TELEGRAM_API_HASH` qo'shilsa, konteyner ichida local Bot API server o'zi ishga tushadi (2 GB gacha). Bunda bot avval cloud API'dan `logOut` qilingan bo'lishi kerak.

Boshqa hosting uchun [local Bot API server](https://github.com/tdlib/telegram-bot-api) ko'taring (u bilan 2 GB gacha) va `.env` da:
```
TELEGRAM_API_SERVER=http://localhost:8081
```

## YouTube -> Reels kliplar

Botga YouTube link yuborasiz → Gemini videoni ko'radi, spikerlarni ajratadi → "qaysi biri siz?" → sizning eng zo'r 25-60 s bo'laklaringizni 9:16 qilib (kadr yuzingizga qarab), tepasiga hook yozuvi bilan qaytaradi.

Variables:
- `GEMINI_API_KEY` — https://aistudio.google.com/apikey (bepul tier bor)
- `GEMINI_MODEL` — ixtiyoriy, default `gemini-flash-latest`
- `CLIPS_MAX` — bitta videodan nechta klip (default 5)
- `YT_COOKIES` — YouTube serverdan yuklashni bloklasa: brauzerdan eksport qilingan `cookies.txt` matni

Video **public** yoki **unlisted** bo'lishi kerak (Gemini private videoni ko'rmaydi).
