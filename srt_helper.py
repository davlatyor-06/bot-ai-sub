import re
from pathlib import Path

class SRTHelper:
    @staticmethod
    def clean_srt(raw_text: str) -> str:
        """
        AI javobidagi ortiqcha markdown (```srt ... ```) va bo'shliqlarni tozalash.
        """
        text = raw_text.strip()
        text = re.sub(r"^```(?:srt)?\s*", "", text, flags=re.IGNORECASE)
        text = re.sub(r"\s*```$", "", text)
        text = text.replace("\r\n", "\n").replace("\r", "\n")
        text = re.sub(r"\n{3,}", "\n\n", text)
        return text.strip() + "\n"

    @staticmethod
    def validate_srt(content: str) -> bool:
        """SRT formati to'g'riligini tekshirish (kamida 1 ta '-->' vaqt belgisi bo'lishi kerak)"""
        return "-->" in content

    @staticmethod
    def count_srt_cues(content: str) -> int:
        """Subtitr qismlari (cues) sonini hisoblash"""
        return len(re.findall(r"\d+\s*\n\d{2}:\d{2}:\d{2}", content)) or len(re.findall(r"-->", content))

    @staticmethod
    def get_srt_preview(content: str, max_items: int = 5) -> str:
        """Telegram xabari uchun chiroyli qisqa preview matn tayyorlash"""
        pattern = re.compile(
            r"(\d+)\s*\n(\d{2}:\d{2}:\d{2}),\d{3}\s*-->\s*(\d{2}:\d{2}:\d{2}),\d{3}\s*\n(.*?)(?=\n\n|\Z)",
            re.DOTALL
        )
        matches = list(pattern.finditer(content))
        if not matches:
            lines = [line.strip() for line in content.split("\n") if line.strip() and not line.strip().isdigit() and "-->" not in line]
            return "\n".join(f"• {l}" for l in lines[:max_items])

        preview_lines = []
        for i, match in enumerate(matches[:max_items]):
            start_time = match.group(2)
            if start_time.startswith("00:"):
                start_time = start_time[3:]
            text = match.group(4).replace("\n", " ").strip()
            preview_lines.append(f"⏱ <code>{start_time}</code> ➔ {text}")

        total = len(matches)
        if total > max_items:
            preview_lines.append(f"<i>... yana {total - max_items} ta subtitr qatori mavjud</i>")

        return "\n".join(preview_lines)

    @staticmethod
    def srt_to_plain_text(content: str) -> str:
        """SRT formatidan vaqt belgilari va raqamlarni olib tashlab, sof matn ajratish"""
        lines = content.split("\n")
        text_lines = []
        for line in lines:
            line_str = line.strip()
            if not line_str or line_str.isdigit() or "-->" in line_str:
                continue
            text_lines.append(line_str)
        return "\n".join(text_lines)

    @staticmethod
    def seconds_to_srt_time(seconds: float) -> str:
        """Sekundlarni 00:00:00,000 SRT vaqt formatiga o'tkazish"""
        if seconds < 0:
            seconds = 0.0
        hours = int(seconds // 3600)
        minutes = int((seconds % 3600) // 60)
        secs = int(seconds % 60)
        millis = int(round((seconds - int(seconds)) * 1000))
        if millis >= 1000:
            secs += 1
            millis -= 1000
        return f"{hours:02d}:{minutes:02d}:{secs:02d},{millis:03d}"

    @staticmethod
    def parse_srt_time(t_str: str) -> float:
        """00:00:00,000 vaqt matnini sekundlarga aylantirish"""
        parts = t_str.strip().split(":")
        h = int(parts[0])
        m = int(parts[1])
        s_parts = parts[2].replace(".", ",").split(",")
        s = int(s_parts[0])
        ms = int(s_parts[1]) if len(s_parts) > 1 else 0
        return h * 3600 + m * 60 + s + ms / 1000.0

    @classmethod
    def words_to_dynamic_srt(cls, words, max_words: int = 3, pause_threshold: float = 0.4) -> str:
        """
        Whisper so'zlar ro'yxatidan har bir subtitr blokida MAKSIMAL 3 ta,
        MINIMAL 1 ta so'zdan iborat dinamik SRT yaratish (Reels / Shorts / TikTok uslubida).
        """
        chunks = []
        current_chunk = []

        for w in words:
            w_text = (w.word if hasattr(w, "word") else w.get("word", "")).strip()
            if not w_text:
                continue

            w_start = w.start if hasattr(w, "start") else w.get("start", 0.0)
            w_end = w.end if hasattr(w, "end") else w.get("end", 0.0)

            if current_chunk:
                prev_w = current_chunk[-1]
                prev_end = prev_w.end if hasattr(prev_w, "end") else prev_w.get("end", 0.0)
                prev_text = (prev_w.word if hasattr(prev_w, "word") else prev_w.get("word", "")).strip()

                pause = w_start - prev_end
                has_strong_punct = prev_text.endswith((".", "?", "!", ";"))
                has_soft_punct = prev_text.endswith(",")

                # Agar 3 ta so'z bo'lsa yoki jumla tugagan bo'lsa yoki oradagi pauza katta bo'lsa
                if len(current_chunk) >= max_words or has_strong_punct or pause >= pause_threshold:
                    chunks.append(current_chunk)
                    current_chunk = []
                elif len(current_chunk) >= 2 and has_soft_punct:
                    chunks.append(current_chunk)
                    current_chunk = []

            current_chunk.append(w)

        if current_chunk:
            chunks.append(current_chunk)

        srt_blocks = []
        for idx, chunk in enumerate(chunks, 1):
            c_start = chunk[0].start if hasattr(chunk[0], "start") else chunk[0].get("start", 0.0)
            c_end = chunk[-1].end if hasattr(chunk[-1], "end") else chunk[-1].get("end", 0.0)
            if c_end <= c_start:
                c_end = c_start + 0.35
            c_text = " ".join((w.word if hasattr(w, "word") else w.get("word", "")).strip() for w in chunk)
            srt_blocks.append(f"{idx}\n{cls.seconds_to_srt_time(c_start)} --> {cls.seconds_to_srt_time(c_end)}\n{c_text}")

        return "\n\n".join(srt_blocks) + "\n"

    @classmethod
    def segments_to_srt(cls, segments, max_words: int = 3) -> str:
        """Whisper segmentlarini har bir blokda 1-3 ta so'zdan bo'lib SRT ga aylantirish"""
        srt_blocks = []
        global_index = 1

        for seg in segments:
            text = seg.text.strip() if hasattr(seg, "text") else seg.get("text", "").strip()
            if not text:
                continue
            start_sec = seg.start if hasattr(seg, "start") else seg.get("start", 0.0)
            end_sec = seg.end if hasattr(seg, "end") else seg.get("end", 0.0)
            if end_sec <= start_sec:
                end_sec = start_sec + 0.5

            words = text.split()
            if len(words) <= max_words:
                srt_blocks.append(f"{global_index}\n{cls.seconds_to_srt_time(start_sec)} --> {cls.seconds_to_srt_time(end_sec)}\n{text}")
                global_index += 1
                continue

            # 1-3 ta so'zlik guruhlarga ajratish
            chunks = []
            i = 0
            while i < len(words):
                rem = len(words) - i
                take = 2 if rem == 4 else min(max_words, rem)
                chunks.append(words[i:i+take])
                i += take

            total_chars = sum(len(w) for w in words)
            dur = end_sec - start_sec
            curr_start = start_sec

            for c in chunks:
                c_chars = sum(len(w) for w in c)
                c_dur = dur * (c_chars / total_chars) if total_chars > 0 else dur / len(chunks)
                c_end = curr_start + c_dur
                c_text = " ".join(c)
                srt_blocks.append(f"{global_index}\n{cls.seconds_to_srt_time(curr_start)} --> {cls.seconds_to_srt_time(c_end)}\n{c_text}")
                global_index += 1
                curr_start = c_end

        return "\n\n".join(srt_blocks) + "\n"

    @classmethod
    def split_existing_srt_to_dynamic(cls, srt_content: str, max_words: int = 3) -> str:
        """Har qanday mavjud SRT matnini qat'iy 1-3 ta so'zdan iborat bloklarga bo'lish kafolati"""
        pattern = re.compile(
            r"(\d+)\s*\n(\d{2}:\d{2}:\d{2}[,\.]\d{3})\s*-->\s*(\d{2}:\d{2}:\d{2}[,\.]\d{3})\s*\n(.*?)(?=\n\s*\n|\Z)",
            re.DOTALL
        )
        matches = list(pattern.finditer(srt_content))
        if not matches:
            return srt_content

        global_blocks = []
        idx = 1

        for m in matches:
            start_sec = cls.parse_srt_time(m.group(2))
            end_sec = cls.parse_srt_time(m.group(3))
            text = m.group(4).replace("\n", " ").strip()
            words = text.split()
            if not words:
                continue

            if len(words) <= max_words:
                global_blocks.append(f"{idx}\n{cls.seconds_to_srt_time(start_sec)} --> {cls.seconds_to_srt_time(end_sec)}\n{text}")
                idx += 1
                continue

            chunks = []
            i = 0
            while i < len(words):
                rem = len(words) - i
                take = 2 if rem == 4 else min(max_words, rem)
                chunks.append(words[i:i+take])
                i += take

            total_chars = sum(len(w) for w in words)
            dur = end_sec - start_sec
            curr_start = start_sec
            for c in chunks:
                c_chars = sum(len(w) for w in c)
                c_dur = dur * (c_chars / total_chars) if total_chars > 0 else dur / len(chunks)
                c_end = curr_start + c_dur
                c_text = " ".join(c)
                global_blocks.append(f"{idx}\n{cls.seconds_to_srt_time(curr_start)} --> {cls.seconds_to_srt_time(c_end)}\n{c_text}")
                idx += 1
                curr_start = c_end

        return "\n\n".join(global_blocks) + "\n"

    @classmethod
    def offset_srt_timestamps(cls, content: str, offset_sec: float) -> str:
        """SRT vaqt belgilariga offset_sec sekund qo'shish"""
        pattern = re.compile(r"(\d{2}):(\d{2}):(\d{2}),(\d{3})\s*-->\s*(\d{2}):(\d{2}):(\d{2}),(\d{3})")
        def shift(match):
            h1, m1, s1, ms1, h2, m2, s2, ms2 = map(int, match.groups())
            t1 = h1 * 3600 + m1 * 60 + s1 + ms1 / 1000.0 + offset_sec
            t2 = h2 * 3600 + m2 * 60 + s2 + ms2 / 1000.0 + offset_sec
            return f"{cls.seconds_to_srt_time(t1)} --> {cls.seconds_to_srt_time(t2)}"
        return pattern.sub(shift, content)

    @classmethod
    def merge_srt_chunks(cls, srt_chunks_with_offsets: list[tuple[str, float]]) -> str:
        """Bir nechta audio bo'laklarining SRT natijalarini to'g'ri vaqt va raqamlar bilan birlashtirish"""
        all_blocks = []
        global_index = 1
        for srt_text, offset in srt_chunks_with_offsets:
            shifted = cls.offset_srt_timestamps(srt_text, offset)
            pattern = re.compile(
                r"(\d+)\s*\n(\d{2}:\d{2}:\d{2},\d{3}\s*-->\s*\d{2}:\d{2}:\d{2},\d{3})\s*\n(.*?)(?=\n\n|\Z)",
                re.DOTALL
            )
            for m in pattern.finditer(shifted):
                timecode = m.group(2)
                text = m.group(3).strip()
                if text:
                    all_blocks.append(f"{global_index}\n{timecode}\n{text}")
                    global_index += 1

        return "\n\n".join(all_blocks) + "\n"

    @staticmethod
    def format_duration(seconds: float) -> str:
        """Sekundlarni MM:SS yoki HH:MM:SS formatiga o'tkazish"""
        s = int(seconds)
        h = s // 3600
        m = (s % 3600) // 60
        sec = s % 60
        if h > 0:
            return f"{h:02d}:{m:02d}:{sec:02d}"
        return f"{m:02d}:{sec:02d}"
