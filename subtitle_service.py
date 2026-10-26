import asyncio
import os
import re
import io
import logging
from pathlib import Path
from config import Config
try:
    from utils.srt_helper import SRTHelper
except (ModuleNotFoundError, ImportError):
    from srt_helper import SRTHelper

logger = logging.getLogger("SubtitleService")

# OpenAI / Groq
try:
    from openai import AsyncOpenAI
except ImportError:
    AsyncOpenAI = None

# Gemini
try:
    from google import genai
    from google.genai import types
except ImportError:
    genai = None


class SubtitleService:
    def __init__(self):
        # Groq client
        self.groq_client = None
        if Config.GROQ_API_KEY and AsyncOpenAI:
            self.groq_client = AsyncOpenAI(
                api_key=Config.GROQ_API_KEY,
                base_url="https://api.groq.com/openai/v1"
            )

        # OpenAI client
        self.openai_client = None
        if Config.OPENAI_API_KEY and AsyncOpenAI:
            self.openai_client = AsyncOpenAI(api_key=Config.OPENAI_API_KEY)

        # Gemini client
        self.gemini_client = None
        if Config.GEMINI_API_KEY and genai:
            self.gemini_client = genai.Client(api_key=Config.GEMINI_API_KEY)

    async def transcribe(self, audio_path: str | Path, language: str = "uz") -> str:
        """
        Audio faylni o'zbekcha SRT formatida transkripsiya qiladi.
        Agar audio 22 MB dan katta bo'lsa (uzoq videolar uchun), avtomatik bo'laklab transkripsiya qiladi.
        """
        try:
            from services.ffmpeg_service import FFmpegService
        except (ModuleNotFoundError, ImportError):
            from ffmpeg_service import FFmpegService
        audio_path = Path(audio_path)
        if not audio_path.exists():
            raise FileNotFoundError(f"Audio fayl topilmadi: {audio_path}")

        chunks = await FFmpegService.split_audio_if_needed(audio_path)
        if len(chunks) <= 1:
            return await self._transcribe_single(chunks[0][0], language)

        logger.info(f"Katta audio fayl {len(chunks)} ta bo'lakda transkripsiya qilinmoqda...")
        srt_chunks = []
        for chunk_file, offset in chunks:
            chunk_srt = await self._transcribe_single(chunk_file, language)
            srt_chunks.append((chunk_srt, offset))

        return SRTHelper.merge_srt_chunks(srt_chunks)

    async def _transcribe_single(self, audio_path: Path, language: str = "uz") -> str:
        """Bitta audio faylni transkripsiya qilish (provayderlar navbati bilan)"""
        provider = Config.get_active_provider()
        audio_path = Path(audio_path)

        if not audio_path.exists():
            raise FileNotFoundError(f"Audio fayl topilmadi: {audio_path}")

        # Provayderlar navbati
        providers_to_try = []
        if provider == "groq" and self.groq_client:
            providers_to_try = ["groq", "openai", "gemini"]
        elif provider == "openai" and self.openai_client:
            providers_to_try = ["openai", "groq", "gemini"]
        elif provider == "gemini" and self.gemini_client:
            providers_to_try = ["gemini", "groq", "openai"]
        else:
            # Mavjudlariga qarab
            if self.groq_client:
                providers_to_try.append("groq")
            if self.openai_client:
                providers_to_try.append("openai")
            if self.gemini_client:
                providers_to_try.append("gemini")

        last_error = None
        for p in providers_to_try:
            try:
                logger.info(f"Subtitr generatsiyasi boshlandi. Provayder: {p.upper()}")
                if p == "groq":
                    srt_text = await self._transcribe_groq(audio_path, language)
                elif p == "openai":
                    srt_text = await self._transcribe_openai(audio_path, language)
                elif p == "gemini":
                    srt_text = await self._transcribe_gemini(audio_path, language)
                else:
                    continue

                cleaned_srt = SRTHelper.clean_srt(srt_text)
                if SRTHelper.validate_srt(cleaned_srt):
                    # 1. AI orqali imlo, grammatika va noto'g'ri eshitilgan so'zlarni tuzatish
                    logger.info("AI orqali subtitr imlosi va grammatikasi tekshirilmoqda...")
                    corrected_srt = await self.correct_srt_with_ai(cleaned_srt)
                    # 2. Har bir blokda qat'iy 1-3 ta so'z bo'lishini kafolatlash
                    dynamic_srt = SRTHelper.split_existing_srt_to_dynamic(corrected_srt, max_words=3)
                    logger.info(f"Subtitr muvaffaqiyatli olindi va imlosi to'g'rilandi ({p.upper()})")
                    return dynamic_srt
                else:
                    logger.warning(f"{p} javobida to'g'ri SRT formati topilmadi, keyingi provayder sinaladi.")
            except Exception as e:
                logger.error(f"{p.upper()} orqali transkripsiyada xatolik: {e}")
                last_error = e

        error_message = (
            f"Barcha AI provayderlarida xatolik yuz berdi. Oxirgi xatolik: {last_error}\n"
            "Maslahat: .env faylida to'g'ri API kalit kiritilganligiga yoki limit mavjudligiga ishonch hosil qiling."
        )
        raise RuntimeError(error_message)

    async def _transcribe_groq(self, audio_path: Path, language: str) -> str:
        """Groq Whisper Large V3 orqali tezkor SRT generatsiya (so'zlar darajasida)"""
        if not self.groq_client:
            raise RuntimeError("GROQ_API_KEY mavjud emas")

        with open(audio_path, "rb") as f:
            audio_bytes = f.read()

        file_tuple = (audio_path.name, audio_bytes, "audio/mp3")
        
        # Whisper uchun o'zbek tili adabiy imlo konteksti (atamalar va so'zlar to'g'ri tanilishi uchun)
        uzbek_prompt = (
            "O'zbek tilidagi adabiy va to'g'ri nutq. So'zlar to'g'ri imlo bilan, o' va g' harflari, "
            "tinish belgilari saqlansin: Inseminatsiya, EKU, tahlillar, jarayoni, kimlarga qilinadi, "
            "oddiyroq, arzon usul hisoblanadi, homiladorlik rejalashtirish, shifokor tekshiruvi, "
            "ideal holatda, ko'pchilik, natijalar."
        )

        response = await self.groq_client.audio.transcriptions.create(
            file=file_tuple,
            model="whisper-large-v3",
            response_format="verbose_json",
            timestamp_granularities=["word", "segment"],
            language=language,
            prompt=uzbek_prompt,
            temperature=0.0
        )
        # 1. Segmentlar orqali matnni to'liq, so'zlarni tushirib qoldirmasdan 1-3 ta so'zdan ajratish
        if hasattr(response, "segments") and response.segments:
            return SRTHelper.segments_to_srt(response.segments, max_words=3)

        # 2. So'zlar darajasida (zaxira)
        if hasattr(response, "words") and response.words:
            return SRTHelper.words_to_dynamic_srt(response.words, max_words=3, pause_threshold=0.4)
        
        # 3. Matn darajasida
        raw_text = getattr(response, "text", str(response)).strip()
        if not raw_text:
            return ""
        dummy_srt = f"1\n00:00:00,000 --> 00:00:05,000\n{raw_text}\n"
        return SRTHelper.split_existing_srt_to_dynamic(dummy_srt, max_words=3)

    async def correct_srt_with_ai(self, srt_content: str) -> str:
        """
        SRT subtitrdagi barcha fonetik xato, sheva va imlo xatolarini
        AI (Qwen) yordamida to'g'ri o'zbek adabiy tiliga tuzatadi.
        """
        if not self.groq_client:
            return srt_content

        pattern = re.compile(
            r"(\d+)\s*\n(\d{2}:\d{2}:\d{2}[,\.]\d{3}\s*-->\s*\d{2}:\d{2}:\d{2}[,\.]\d{3})\s*\n(.*?)(?=\n\s*\n|\Z)",
            re.DOTALL
        )
        matches = list(pattern.finditer(srt_content))
        if not matches:
            return srt_content

        # 25 tadan blok qilib bo'laklarga ajratish (1-2 ta so'rov, tezkor va 429 limitsiz)
        batch_size = 25
        batches = []
        for i in range(0, len(matches), batch_size):
            chunk_matches = matches[i:i + batch_size]
            chunk_text = "\n\n".join(m.group(0).strip() for m in chunk_matches)
            batches.append(chunk_text)

        corrected_parts = []
        for b_idx, batch in enumerate(batches):
            try:
                prompt = f"""Sen professional o'zbek tili muharririsan. Whisper nutqni tanish modeli o'zbekcha so'zlarni xato, noaniq yoki shevada eshitgan bo'lishi mumkin.
Masalan:
- 'Intimidatsiya jarayonu' aslida 'Inseminatsiya jarayoni'
- 'nima uzu' -> 'nima o'zi'
- 'kimlegi qilinadug' -> 'kimlarga qilinadi'
- 'ekodan oddiraq va arzon usulx soplanadi' -> 'EKU dan oddiyroq va arzon usul hisoblanadi'
- 'xama taklillaru zor, idealni xaladda' -> 'hamma tahlillar zo'r, ideal holatda'

VAZIFA:
Quyidagi SRT dagi barcha xato so'zlarni kontekstga qarab to'g'ri o'zbek adabiy tiliga, to'g'ri imlo va grammatika bilan tuzat.

QAT'IY QOIDALAR:
1. Vaqt belgilarini (00:00:00,000 --> 00:00:00,000) va raqamlarni (1, 2, 3...) BIR HARFINI HAM O'ZGARTIRMA!
2. Har bir subtitr blokida 1-3 ta so'z saqlansin.
3. Faqat to'g'rilangan SRT matnini qaytar. Hech qanday so'zboshi, izoh yoki markdown yozma!

SRT:
{batch}"""

                res = await self.groq_client.chat.completions.create(
                    model="qwen/qwen3.8-27b",
                    messages=[{"role": "user", "content": prompt}],
                    temperature=0.0,
                    max_tokens=600
                )
                ans = SRTHelper.clean_srt(res.choices[0].message.content.strip())
                if SRTHelper.validate_srt(ans):
                    corrected_parts.append(ans)
                else:
                    corrected_parts.append(batch)
                
                if b_idx < len(batches) - 1:
                    await asyncio.sleep(0.5)
            except Exception as e:
                logger.warning(f"AI imlo tuzatishda xatolik ({b_idx}-partiya): {e}")
                corrected_parts.append(batch)

        full_corrected = "\n\n".join(corrected_parts)
        return SRTHelper.split_existing_srt_to_dynamic(full_corrected, max_words=3)

    async def _transcribe_openai(self, audio_path: Path, language: str) -> str:
        """OpenAI Whisper-1 orqali SRT generatsiya (so'zlar darajasida)"""
        if not self.openai_client:
            raise RuntimeError("OPENAI_API_KEY mavjud emas")

        with open(audio_path, "rb") as f:
            audio_bytes = f.read()

        file_tuple = (audio_path.name, audio_bytes, "audio/mp3")
        response = await self.openai_client.audio.transcriptions.create(
            file=file_tuple,
            model="whisper-1",
            response_format="verbose_json",
            timestamp_granularities=["word", "segment"],
            language=language,
            temperature=0.0
        )
        if hasattr(response, "words") and response.words:
            return SRTHelper.words_to_dynamic_srt(response.words, max_words=3, pause_threshold=0.4)
        if hasattr(response, "segments") and response.segments:
            return SRTHelper.segments_to_srt(response.segments, max_words=3)
        return SRTHelper.split_existing_srt_to_dynamic(getattr(response, "text", str(response)), max_words=3)

    async def _transcribe_gemini(self, audio_path: Path, language: str) -> str:
        """Google Gemini orqali audiodan SRT generatsiya"""
        if not self.gemini_client:
            raise RuntimeError("GEMINI_API_KEY mavjud emas")

        with open(audio_path, "rb") as f:
            audio_bytes = f.read()

        prompt = (
            "Ushbu audio yozuvdagi so'zlarni aniq o'zbek tilida eshiting va to'g'ridan-to'g'ri standart SRT (SubRip) subtitr formatida chiqaring.\n"
            "Talablar:\n"
            "1. Har bir subtitr bloki raqam, vaqt oralig'i (00:00:00,000 --> 00:00:00,000) va matndan iborat bo'lsin.\n"
            "2. O'zbek tilining grammatikasi va tinish belgilariga to'liq rioya qiling.\n"
            "3. Faqat sof SRT matnini qaytaring. Hech qanday qo'shimcha izoh, kirish so'z yoki markdown belgilari (```srt) yozmang."
        )

        # Gemini model nomlari: gemini-3.8-flash, gemini-2.5-flash
        model_names = ["gemini-3.8-flash", "gemini-2.5-flash", "gemini-flash-latest"]
        for m in model_names:
            try:
                response = await self.gemini_client.aio.models.generate_content(
                    model=m,
                    contents=[
                        types.Part.from_bytes(data=audio_bytes, mime_type="audio/mp3"),
                        prompt
                    ]
                )
                if response and response.text:
                    return response.text
            except Exception as e:
                logger.warning(f"Gemini {m} modelida xato: {e}")
                continue

        raise RuntimeError("Gemini modellarining birortasi orqali subtitr olib bo'lmadi")

    async def translate_srt(self, srt_content: str, target_lang: str = "en") -> str:
        """
        Mavjud SRT subtitr faylining matnini vaqt belgilarini (timestamps) o'zgartirmagan holda
        boshqa tilga (masalan: ingliz yoki rus) tarjima qilish.
        """
        lang_names = {
            "en": "English",
            "ru": "Russian",
            "uz": "Uzbek"
        }
        target_name = lang_names.get(target_lang, target_lang)

        prompt = (
            f"You are a professional subtitle translator. Translate the dialogue in the following SRT subtitles into {target_name}.\n"
            "CRITICAL RULES:\n"
            "1. Keep all sequence numbers and timecodes (00:00:00,000 --> 00:00:00,000) EXACTLY unchanged.\n"
            "2. Only translate the text dialogue itself.\n"
            "3. Return ONLY valid SRT output. No explanations, no markdown blocks.\n\n"
            f"{srt_content}"
        )

        # Groq or OpenAI or Gemini
        if self.groq_client:
            res = await self.groq_client.chat.completions.create(
                model="llama-3.3-70b-versatile",
                messages=[{"role": "user", "content": prompt}],
                temperature=0.2
            )
            return SRTHelper.clean_srt(res.choices[0].message.content)
        elif self.openai_client:
            res = await self.openai_client.chat.completions.create(
                model="gpt-4o-mini",
                messages=[{"role": "user", "content": prompt}],
                temperature=0.2
            )
            return SRTHelper.clean_srt(res.choices[0].message.content)
        elif self.gemini_client:
            res = await self.gemini_client.aio.models.generate_content(
                model="gemini-3.8-flash",
                contents=prompt
            )
            return SRTHelper.clean_srt(res.text)
        
        raise RuntimeError("Tarjima qilish uchun faol AI mijoz topilmadi")
