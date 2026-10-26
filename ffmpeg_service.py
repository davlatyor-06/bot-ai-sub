import os
import re
import shutil
import asyncio
import logging
from pathlib import Path

logger = logging.getLogger("FFmpegService")

class FFmpegService:
    _ffmpeg_exe: str | None = None

    @classmethod
    def get_ffmpeg_exe(cls) -> str:
        """FFmpeg binar faylini aniqlash"""
        if cls._ffmpeg_exe:
            return cls._ffmpeg_exe

        # 1. imageio_ffmpeg paketi orqali tekshirish
        try:
            import imageio_ffmpeg
            cls._ffmpeg_exe = imageio_ffmpeg.get_ffmpeg_exe()
            logger.info(f"imageio_ffmpeg topildi: {cls._ffmpeg_exe}")
            return cls._ffmpeg_exe
        except Exception:
            pass

        # 2. Tizim PATH dan tekshirish
        system_ffmpeg = shutil.which("ffmpeg")
        if system_ffmpeg:
            cls._ffmpeg_exe = system_ffmpeg
            logger.info(f"Tizim FFmpeg topildi: {cls._ffmpeg_exe}")
            return cls._ffmpeg_exe

        raise RuntimeError("FFmpeg topilmadi! Iltimos, ffmpeg o'rnating yoki imageio-ffmpeg paketini tekshiring.")

    @classmethod
    async def extract_audio(cls, video_path: str | Path, output_audio_path: str | Path) -> None:
        """
        Videodan 16kHz mono MP3 formatida audio ajratib oladi.
        Bu format AI (Whisper / Gemini) uchun ideal va fayl hajmi juda kichik bo'ladi.
        """
        ffmpeg_exe = cls.get_ffmpeg_exe()
        video_path = str(Path(video_path).resolve())
        output_audio_path = str(Path(output_audio_path).resolve())

        # -vn: video yo'q, -acodec libmp3lame, -ar 16000: 16kHz, -ac 1: mono, -b:a 64k: 64kbps
        cmd = [
            ffmpeg_exe,
            "-y",
            "-i", video_path,
            "-vn",
            "-acodec", "libmp3lame",
            "-ar", "16000",
            "-ac", "1",
            "-b:a", "64k",
            output_audio_path
        ]

        logger.info(f"Audioni ajratish boshlandi: {video_path} -> {output_audio_path}")
        process = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )
        _, stderr = await process.communicate()

        if process.returncode != 0:
            error_msg = stderr.decode(errors="ignore")
            logger.error(f"FFmpeg audio ajratishda xatolik: {error_msg}")
            raise RuntimeError(f"Audioni ajratib bo'lmadi: {error_msg[-300:]}")

        logger.info(f"Audio muvaffaqiyatli ajratildi: {output_audio_path}")

    @classmethod
    async def split_audio_if_needed(
        cls,
        audio_path: str | Path,
        max_bytes: int = 22 * 1024 * 1024,
        segment_seconds: int = 600
    ) -> list[tuple[Path, float]]:
        """
        Agar audio fayl hajmi max_bytes (22 MB) dan katta bo'lsa, uni 10 daqiqalik bo'laklarga ajratadi.
        Qaytaradi: [(chunk_path, offset_seconds), ...]
        """
        p = Path(audio_path).resolve()
        if p.stat().st_size <= max_bytes:
            return [(p, 0.0)]

        ffmpeg_exe = cls.get_ffmpeg_exe()
        parent_dir = p.parent
        chunk_pattern = str(parent_dir / "chunk_%03d.mp3")

        cmd = [
            ffmpeg_exe,
            "-y",
            "-i", str(p),
            "-f", "segment",
            "-segment_time", str(segment_seconds),
            "-c", "copy",
            chunk_pattern
        ]

        logger.info(f"Katta audio faylni bo'laklash: {p.name} ({p.stat().st_size // (1024*1024)} MB)")
        process = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )
        await process.communicate()

        chunk_files = sorted(parent_dir.glob("chunk_*.mp3"))
        if not chunk_files:
            return [(p, 0.0)]

        results = []
        for i, chunk in enumerate(chunk_files):
            offset = i * float(segment_seconds)
            results.append((chunk, offset))

        logger.info(f"Audio {len(results)} ta bo'lakka ajratildi.")
        return results

    @classmethod
    async def burn_subtitles(
        cls,
        video_path: str | Path,
        srt_path: str | Path,
        output_video_path: str | Path
    ) -> None:
        """
        SRT subtitr faylini videoga qattiq yopishtiradi (Hardsub).
        Zamonaviy oq rangli, qora hoshiyali va chiroyli shrift bilan.
        """
        ffmpeg_exe = cls.get_ffmpeg_exe()
        video_path = str(Path(video_path).resolve())
        srt_path = str(Path(srt_path).resolve())
        output_video_path = str(Path(output_video_path).resolve())

        # Windows uchun yo'l belgilari va ikki nuqtani escape qilish
        escaped_srt = srt_path.replace("\\", "/").replace(":", r"\:")
        
        # Chiroyli dinamik subtitr stili (1-3 so'z uchun qulay, qalin oq va aniq hoshiya):
        style = (
            "FontSize=20,"
            "Bold=1,"
            "PrimaryColour=&H00FFFFFF,"
            "OutlineColour=&H00000000,"
            "BackColour=&H80000000,"
            "BorderStyle=3,"
            "Outline=1.5,"
            "Shadow=0,"
            "MarginV=30"
        )
        vf = f"subtitles='{escaped_srt}':force_style='{style}'"

        cmd = [
            ffmpeg_exe,
            "-y",
            "-i", video_path,
            "-vf", vf,
            "-c:a", "copy",
            "-c:v", "libx264",
            "-preset", "fast",
            "-crf", "22",
            output_video_path
        ]

        logger.info(f"Videoga subtitr yopishtirish boshlandi: {output_video_path}")
        process = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )
        _, stderr = await process.communicate()

        if process.returncode != 0:
            error_msg = stderr.decode(errors="ignore")
            logger.error(f"FFmpeg hardsub xatolik: {error_msg}")
            raise RuntimeError(f"Subtitrni videoga yopishtirib bo'lmadi: {error_msg[-300:]}")

        logger.info(f"Subtitr videoga yopishtirildi: {output_video_path}")

    @classmethod
    async def audio_to_subtitled_video(
        cls,
        audio_path: str | Path,
        srt_path: str | Path,
        output_video_path: str | Path
    ) -> None:
        """
        Ovozli xabar yoki audio fayldan 9:16 vertikal subtitrli video (Reels/Shorts uslubida) yaratish.
        """
        ffmpeg_exe = cls.get_ffmpeg_exe()
        audio_path = str(Path(audio_path).resolve())
        srt_path = str(Path(srt_path).resolve())
        output_video_path = str(Path(output_video_path).resolve())

        escaped_srt = srt_path.replace("\\", "/").replace(":", r"\:")
        style = (
            "FontSize=22,"
            "Bold=1,"
            "PrimaryColour=&H00FFFFFF,"
            "OutlineColour=&H00000000,"
            "BackColour=&H80000000,"
            "BorderStyle=3,"
            "Outline=1.5,"
            "Shadow=0,"
            "MarginV=45"
        )
        vf = f"subtitles='{escaped_srt}':force_style='{style}'"

        cmd = [
            ffmpeg_exe,
            "-y",
            "-f", "lavfi",
            "-i", "color=c=0x11111b:s=720x1280:r=25",
            "-i", audio_path,
            "-vf", vf,
            "-c:a", "aac",
            "-b:a", "128k",
            "-c:v", "libx264",
            "-preset", "ultrafast",
            "-pix_fmt", "yuv420p",
            "-shortest",
            output_video_path
        ]

        logger.info(f"Audiodan subtitrli video yaratish: {output_video_path}")
        process = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )
        _, stderr = await process.communicate()

        if process.returncode != 0:
            error_msg = stderr.decode(errors="ignore")
            logger.error(f"FFmpeg audio->video xatolik: {error_msg}")
            raise RuntimeError(f"Audiodan video yaratib bo'lmadi: {error_msg[-300:]}")

        logger.info(f"Audiodan subtitrli video tayyorlandi: {output_video_path}")

    @classmethod
    async def get_video_duration(cls, file_path: str | Path) -> float:
        """Video yoki audio davomiyligini (sekundda) aniqlash"""
        ffmpeg_exe = cls.get_ffmpeg_exe()
        file_path = str(Path(file_path).resolve())

        cmd = [ffmpeg_exe, "-i", file_path]
        process = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )
        _, stderr = await process.communicate()
        err_text = stderr.decode(errors="ignore")

        match = re.search(r"Duration:\s*(\d+):(\d+):(\d+(?:\.\d+)?)", err_text)
        if match:
            h, m, s = match.groups()
            return int(h) * 3600 + int(m) * 60 + float(s)
        return 0.0
