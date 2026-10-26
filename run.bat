@echo off
chcp 65001 > nul
title QuicSub Bot (Telegram Subtitr Boti)

echo ======================================================
echo    🎬 QuicSub Bot ishga tushirilmoqda...
echo ======================================================

python main.py

if errorlevel 1 (
    echo.
    echo Xatolik yuz berdi. Iltimos, yuqoridagi xabarni o'qing.
    pause
)
