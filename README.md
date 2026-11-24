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
