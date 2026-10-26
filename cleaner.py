import shutil
import time
import logging
from pathlib import Path

logger = logging.getLogger("Cleaner")

class Cleaner:
    @staticmethod
    def cleanup_path(path: str | Path) -> None:
        """Fayl yoki papkani xavfsiz o'chirish"""
        try:
            p = Path(path)
            if not p.exists():
                return
            if p.is_file():
                p.unlink(missing_ok=True)
            elif p.is_dir():
                shutil.rmtree(p, ignore_errors=True)
            logger.debug(f"Tozalandi: {path}")
        except Exception as e:
            logger.warning(f"O'chirishda xatolik ({path}): {e}")

    @staticmethod
    def cleanup_old_temp(temp_dir: Path, max_age_seconds: int = 3600) -> None:
        """Belgilangan vaqtdan (masalan 1 soat) eski bo'lgan vaqtinchalik papkalarni tozalash"""
        try:
            if not temp_dir.exists():
                return
            current_time = time.time()
            for item in temp_dir.iterdir():
                if item.is_dir():
                    mtime = item.stat().st_mtime
                    if current_time - mtime > max_age_seconds:
                        shutil.rmtree(item, ignore_errors=True)
                        logger.info(f"Eski vaqtinchalik papka tozalandi: {item.name}")
        except Exception as e:
            logger.warning(f"Eski fayllarni tozalashda xatolik: {e}")
