#!/bin/bash
# =======================================================
# QuicSub Bot - Linux / VPS ishga tushirish skripti
# =======================================================

echo "=== QuicSub Bot ishga tushirilmoqda ==="

# Virtual muhit mavjud bo'lsa faollashtirish
if [ -d "venv" ]; then
    source venv/bin/activate
fi

# Tizimda ffmpeg o'rnatilganligini tekshirish
if ! command -v ffmpeg &> /dev/null; then
    echo "DIQQAT: ffmpeg topilmadi! O'rnatish uchun: sudo apt update && sudo apt install -y ffmpeg"
fi

python3 main.py
