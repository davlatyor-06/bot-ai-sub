# 🚀 QuicSub Bot - Hostinga Joylash Bo'yicha To'liq Qo'llanma

Ushbu qo'llanma botni **VPS / Ubuntu serveri**, **Docker** yoki **bulutli hostinglarga** 24/7 uzluksiz ishlash uchun joylash bo'yicha bosqichma-bosqich yo'riqnomadir.

---

## 📂 Loyiha fayllari

```text
quicsub_bot/
├── main.py                # Botning asosiy ishga tushiruvchi fayli
├── config.py              # Sozlamalar va muhit o'zgaruvchilari
├── services/
│   ├── ffmpeg_service.py   # Audio ajratish, optimizatsiya va Hardsub video
│   └── subtitle_service.py # Whisper Large v3 + AI imlo tekshiruvchi
├── utils/
│   ├── srt_helper.py       # SRT formatini tozalash va 1-3 so'zdan bo'lish
│   └── cleaner.py          # Vaqtinchalik fayllarni avtomatik tozalash
├── .env                   # Bot tokeni va AI API kalitlari
├── .env.example           # Namuna sozlamalar
├── requirements.txt       # Python kutubxonalari
├── Dockerfile             # Docker konteyner fayli
├── docker-compose.yml     # Docker Compose fayli
├── start.sh               # Linux ishga tushirish skripti
├── quicsub_bot.service    # 24/7 ishlashi uchun Linux systemd xizmati
└── run.bat                # Windows uchun tezkor ishga tushirish
```

---

## 🖥 1-USUL: Oddiy Linux / VPS (Ubuntu / Debian) Serverga Joylash (Tavsiya etiladi)

Bu Timeweb, Hetzner, DigitalOcean yoki boshqa istalgan VPS serverlar uchun eng qulay usul.

### 1-qadam: Serverga kerakli dasturlarni o'rnatish
SSH orqali serveringizga ulaning va quyidagi buyruqni bajaring:
```bash
sudo apt update && sudo apt install -y python3 python3-pip python3-venv ffmpeg fonts-dejavu-core git
```

### 2-qadam: Loyiha papkasini serverga yuklash
`quicsub_bot` papkasini serverga yuklang (masalan, **FileZilla** yoki **MobaXterm** orqali `/root/quicsub_bot` manziliga).

### 3-qadam: Virtual muhit (venv) yaratish va kutubxonalarni o'rnatish
```bash
cd /root/quicsub_bot
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

### 4-qadam: .env faylini tekshirish
`.env` faylida barcha kalitlar (`BOT_TOKEN`, `GROQ_API_KEY`) to'g'ri yozilganligini tekshiring:
```bash
nano .env
```
*(Chiqish uchun: `Ctrl + X`, keyin `Y` va `Enter`)*

### 5-qadam: Botni 24/7 avtomatik ishlashga qo'yish (systemd)
Server o'chib yonsa ham bot avtomatik ishlab turishi uchun:

1. Xizmat faylini tizimga nusxalang:
```bash
sudo cp quicsub_bot.service /etc/systemd/system/
```
2. Xizmatni faollashtiring va ishga tushiring:
```bash
sudo systemctl daemon-reload
sudo systemctl enable quicsub_bot
sudo systemctl start quicsub_bot
```
3. Bot holatini ko'rish:
```bash
sudo systemctl status quicsub_bot
```
4. Bot loglarini jonli kuzatish:
```bash
journalctl -u quicsub_bot -f
```

---

## 🐳 2-USUL: Docker orqali ishga tushirish (Eng oson)

Agar serveringizda Docker o'rnatilgan bo'lsa, bor-yo'g'i 1 ta buyruq kifoya:

```bash
cd quicsub_bot
docker compose up -d --build
```

* Loglarni ko'rish: `docker compose logs -f`
* Botni to'xtatish: `docker compose down`

---

## ☁️ 3-USUL: Railway / Render / PaaS platformalariga joylash

1. Papkani **GitHub** profilingizga yuklang (repo oching).
2. [Railway.app](https://railway.app) ga kiring, GitHub repoingizni tanlang.
3. Railway loyiha ichidagi `Dockerfile` ni avtomatik aniqlaydi va FFmpeg bilan birga konteyner qilib ishga tushiradi!
4. **Variables** bo'limiga `.env` dagi kalitlarni kiriting:
   - `BOT_TOKEN`
   - `GROQ_API_KEY`
   - `TELEGRAM_API_ID`
   - `TELEGRAM_API_HASH`
   - `MAX_FILE_SIZE_MB=200`
