# Rasmiy telegram-bot-api server (2 GB gacha fayllar uchun)
FROM aiogram/telegram-bot-api:latest AS tgapi

FROM python:3.12-alpine
RUN apk add --no-cache ffmpeg libstdc++ openssl zlib curl nodejs font-dejavu
COPY --from=tgapi /usr/local/bin/telegram-bot-api /usr/local/bin/telegram-bot-api
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
RUN chmod +x start.sh
CMD ["./start.sh"]
