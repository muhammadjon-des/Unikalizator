#!/bin/sh
# TELEGRAM_API_ID/HASH bo'lsa — local Bot API server ham ishga tushadi (2 GB gacha)
if [ -n "$TELEGRAM_API_ID" ] && [ -n "$TELEGRAM_API_HASH" ]; then
  mkdir -p /tmp/tgapi
  telegram-bot-api --api-id="$TELEGRAM_API_ID" --api-hash="$TELEGRAM_API_HASH" \
    --local --dir=/tmp/tgapi --temp-dir=/tmp/tgapi-tmp --http-port=8081 &
  for i in $(seq 1 30); do
    curl -s http://127.0.0.1:8081 >/dev/null 2>&1 && break
    sleep 1
  done
  export TELEGRAM_API_SERVER="http://127.0.0.1:8081"
  echo "Local Bot API server ishga tushdi"
fi
exec python bot.py
