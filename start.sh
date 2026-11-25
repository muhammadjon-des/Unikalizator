#!/bin/sh
# TELEGRAM_API_ID/HASH bo'lsa — local Bot API server ham ishga tushadi (2 GB gacha)
if [ -n "$TELEGRAM_API_ID" ] && [ -n "$TELEGRAM_API_HASH" ]; then
  # Sessiya diskda saqlanadi -> har restartda Telegram'ga qayta login bo'lmaydi
  # (ko'p login = flood control). Fayllar esa vaqtinchalik diskda (/tmp).
  TG_DIR=/tmp/tgapi
  if [ -d /data ]; then TG_DIR=/data/tgapi; fi
  BOT_DIR="$TG_DIR/$BOT_TOKEN"
  mkdir -p "$BOT_DIR" /tmp/tgapi-tmp
  for d in animations documents music photos profile_photos stickers temp thumbnails videos video_notes voice; do
    mkdir -p "/tmp/tgfiles/$d"
    rm -rf "$BOT_DIR/$d"
    ln -s "/tmp/tgfiles/$d" "$BOT_DIR/$d"
  done
  telegram-bot-api --api-id="$TELEGRAM_API_ID" --api-hash="$TELEGRAM_API_HASH" \
    --local --dir="$TG_DIR" --temp-dir=/tmp/tgapi-tmp --http-port=8081 &
  for i in $(seq 1 30); do
    curl -s http://127.0.0.1:8081 >/dev/null 2>&1 && break
    sleep 1
  done
  export TELEGRAM_API_SERVER="http://127.0.0.1:8081"
  echo "Local Bot API server ishga tushdi"
fi
exec python bot.py
