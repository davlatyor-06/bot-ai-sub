import os
from pathlib import Path
from dotenv import load_dotenv

# .env faylini yuklash
BASE_DIR = Path(__file__).resolve().parent
load_dotenv(BASE_DIR / ".env")

class Config:
    BASE_DIR: Path = BASE_DIR

    # Telegram Bot
    BOT_TOKEN: str = os.getenv("BOT_TOKEN", "").strip()
    TELEGRAM_API_ID: int = int(os.getenv("TELEGRAM_API_ID", "31826222"))
    TELEGRAM_API_HASH: str = os.getenv("TELEGRAM_API_HASH", "a48b00fcb1bd0895e9740136eec4c565").strip()

    # AI API kalitlari
    GROQ_API_KEY: str = os.getenv("GROQ_API_KEY", "").strip()
    OPENAI_API_KEY: str = os.getenv("OPENAI_API_KEY", "").strip()
    GEMINI_API_KEY: str = os.getenv("GEMINI_API_KEY", "").strip()

    # Standart AI Provayder (groq | openai | gemini | auto)
    AI_PROVIDER: str = os.getenv("AI_PROVIDER", "auto").strip().lower()

    # Til sozlamasi (O'zbek tili: "uz")
    SUBTITLE_LANGUAGE: str = os.getenv("SUBTITLE_LANGUAGE", "uz").strip()

    # Vaqtinchalik fayllar papkasi
    TEMP_DIR: Path = BASE_DIR / os.getenv("TEMP_DIR", "temp")

    # Telegram bot API yuklash limiti (MB) - Telethon MTProto orqali 200MB va undan ortiq!
    MAX_FILE_SIZE_MB: int = int(os.getenv("MAX_FILE_SIZE_MB", "200"))

    # Administrator va To'lov sozlamalari
    ADMIN_IDS_RAW: str = os.getenv("ADMIN_IDS", "").strip()
    ADMIN_SECRET: str = os.getenv("ADMIN_SECRET", "quicsub2026").strip()

    CARD_NUMBER: str = os.getenv("CARD_NUMBER", "9860170105865001").strip()
    CARD_HOLDER: str = os.getenv("CARD_HOLDER", "Jonibekov D").strip()
    SUBSCRIPTION_PRICE: int = int(os.getenv("SUBSCRIPTION_PRICE", "15000"))
    FREE_LIMIT: int = int(os.getenv("FREE_LIMIT", "4"))
    DB_PATH: Path = BASE_DIR / "quicsub.db"

    @classmethod
    def get_admin_ids(cls) -> list[int]:
        ids = []
        if cls.ADMIN_IDS_RAW:
            for item in cls.ADMIN_IDS_RAW.split(","):
                item = item.strip()
                if item.isdigit():
                    ids.append(int(item))
        return ids

    @classmethod
    def get_active_provider(cls) -> str:
        """Mavjud API kalitiga qarab eng yaxshi provayderni aniqlaydi"""
        if cls.AI_PROVIDER in ["groq", "openai", "gemini"]:
            return cls.AI_PROVIDER

        # Auto rejimida ustuvorlik:
        if cls.GROQ_API_KEY:
            return "groq"
        if cls.OPENAI_API_KEY:
            return "openai"
        if cls.GEMINI_API_KEY:
            return "gemini"
        return "none"

    @classmethod
    def validate(cls) -> tuple[bool, str]:
        """Konfiguratsiyani tekshirish"""
        if not cls.BOT_TOKEN or cls.BOT_TOKEN == "YOUR_TELEGRAM_BOT_TOKEN_HERE":
            return False, "BOT_TOKEN sozlanmagan! Iltimos, .env fayliga Telegram bot tokenini kiriting."
        
        provider = cls.get_active_provider()
        if provider == "none":
            return False, "Hech qanday AI API kaliti topilmadi! .env fayliga GROQ_API_KEY, OPENAI_API_KEY yoki GEMINI_API_KEY kiriting."
        
        cls.TEMP_DIR.mkdir(parents=True, exist_ok=True)
        return True, f"Barcha sozlamalar to'g'ri. Tanlangan AI provayder: {provider.upper()}"
