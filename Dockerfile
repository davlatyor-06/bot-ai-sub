# 1. Rasmiy Python bazaviy tasviri
FROM python:3.11-slim

# Muhit o'zgaruvchilari
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PORT=7860

WORKDIR /app

# 2. Linux tizim paketlari, FFmpeg va shriftlarni o'rnatish
RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    fonts-dejavu-core \
    fonts-liberation \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

# 3. Python kutubxonalarini o'rnatish
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 4. Loyiha fayllarini nusxalash
COPY . .

# 5. Vaqtinchalik fayllar uchun papka va huquqlar
RUN mkdir -p temp && chmod 777 temp

# 6. Hugging Face va boshqa cloud hostinglar uchun 7860 porti
EXPOSE 7860

# 7. Botni ishga tushirish
CMD ["python", "main.py"]
