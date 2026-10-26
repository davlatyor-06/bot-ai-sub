import asyncio
import logging
import os
import re
import socket
import sys
import time
import uuid
from datetime import datetime
from pathlib import Path

from telethon import TelegramClient, events, Button
from telethon.sessions import MemorySession
from telethon.tl.types import DocumentAttributeVideo, DocumentAttributeAudio

from config import Config
from services.ffmpeg_service import FFmpegService
from services.subtitle_service import SubtitleService
from services.db_service import DBService
from utils.srt_helper import SRTHelper
from utils.cleaner import Cleaner

# Log sozlamalari
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%H:%M:%S",
    handlers=[logging.StreamHandler(sys.stdout)]
)
logger = logging.getLogger("Main")

# Xizmatlar
subtitle_service = SubtitleService()
db = DBService()

# Telethon mijozi (MemorySession orqali SQLite database qulflanishining oldi olinadi)
client = TelegramClient(MemorySession(), Config.TELEGRAM_API_ID, Config.TELEGRAM_API_HASH)

VIDEO_EXTENSIONS = {".mp4", ".mov", ".mkv", ".avi", ".webm", ".m4v", ".3gp", ".flv", ".ts", ".wmv"}
AUDIO_EXTENSIONS = {".mp3", ".m4a", ".wav", ".aac", ".ogg", ".opus", ".flac", ".wma", ".oga", ".amr", ".aiff", ".m4b"}


def get_main_keyboard(is_admin: bool = False):
    """Pastki doimiy reply tugmalar menyusi"""
    rows = [
        [Button.text("💎 Oylik obuna sotib olish"), Button.text("📊 Status")],
        [Button.text("✍️ Fikr bildirish")]
    ]
    if is_admin:
        rows.append([Button.text("👑 Admin Panel")])
    return rows


def build_job_buttons(job_id: str, is_video: bool):
    """Natija xabari uchun inline tugmalar"""
    buttons = []
    if is_video:
        buttons.append([Button.inline("🎬 Videoga subtitrni yopishtirish (Hardsub)", f"hardsub:{job_id}")])
    else:
        buttons.append([Button.inline("🎬 Subtitrli videoga aylantirish (Reels/MP4)", f"hardsub:{job_id}")])

    buttons.append([Button.inline("📄 Faqat matn ko'rinishida (.TXT)", f"txt:{job_id}")])
    buttons.append([
        Button.inline("🇷🇺 Ruscha SRT", f"trans:{job_id}:ru"),
        Button.inline("🇬🇧 Inglizcha SRT", f"trans:{job_id}:en")
    ])
    return buttons


# ===================================================================
# BUYRUQLAR (COMMANDS)
# ===================================================================

@client.on(events.NewMessage(pattern=r"^/start$"))
async def handle_start(event):
    """Start buyrug'i - foydalanuvchi talabiga ko'ra matn o'zgarmaydi"""
    user_id = event.sender_id
    sender = await event.get_sender()
    username = getattr(sender, "username", "") or ""
    first_name = getattr(sender, "first_name", "") or ""
    last_name = getattr(sender, "last_name", "") or ""
    full_name = f"{first_name} {last_name}".strip()

    db.get_or_create_user(user_id, username=username, full_name=full_name)
    is_admin = db.is_admin(user_id)

    text = (
        "👋 <b>Assalomu alaykum!</b>\n\n"
        "Men video va ovozli xabarlardan <b>o'zbekcha dinamik subtitr (.srt fayl)</b> tayyorlab beruvchi aqlli botman.\n\n"
        "🎬 <b>Qanday ishlaydi?</b>\n"
        f"1️⃣ Menga <b>Video (MP4)</b> yoki <b>Ovozli xabar (Voice / Audio)</b> yuboring (<b>{Config.MAX_FILE_SIZE_MB} MB gacha</b> qabul qilinadi!).\n"
        "2️⃣ Bot nutqni tahlil qilib, imlo xatolarini to'g'rilaydi va <b>har bir qatorda 1-3 ta so'zdan iborat</b> aniq vaqt belgili SRT subtitr tayyorlaydi.\n"
        "3️⃣ Sizga tayyor <b>.srt fayl</b> yuboriladi!\n\n"
        "✨ <i>Qo'shimcha: Subtitrni videoga yopishtirish (Hardsub) yoki ovozli xabarni to'g'ridan-to'g'ri subtitrli videoga aylantirish (Reels) mumkin!</i>\n\n"
        "🚀 <b>Boshlash uchun hozir video yoki ovozli xabar yuboring!</b>"
    )
    await event.reply(text, parse_mode="html", buttons=get_main_keyboard(is_admin))


@client.on(events.NewMessage(pattern=r"^/help$"))
async def handle_help(event):
    """Yordam buyrug'i"""
    text = (
        "ℹ️ <b>Botdan foydalanish bo'yicha qo'llanma:</b>\n\n"
        "📌 <b>Qo'llab-quvvatlanadigan formatlar:</b>\n"
        "• Video: MP4, MOV, MKV, AVI, WebM\n"
        "• Audio: Ovozli xabarlar, Dumaloq video, MP3, M4A\n\n"
        f"⚖️ <b>Hajm bo'yicha limit:</b> Maksimal <b>{Config.MAX_FILE_SIZE_MB} MB</b> gacha!\n"
        "Telegram MTProto orqali katta hajmdagi videolarni ham muammosiz qabul qiladi.\n\n"
        "💡 <b>Aniq subtitr olish uchun maslahatlar:</b>\n"
        "• Videodagi ovoz tiniq va shovqinsiz bo'lsin.\n"
        "• Orqa fondagi musiqa inson ovozidan baland bo'lmasin.\n\n"
        "⚙️ <b>Menyu buyruqlari:</b>\n"
        "/status - Hisob va limitlar holati\n"
        "/buy - Oylik VIP obuna sotib olish\n"
        "/feedback - Fikr va taklif bildirish\n"
        "/cancel - Har qanday jarayonni bekor qilish"
    )
    await event.reply(text, parse_mode="html")


@client.on(events.NewMessage(pattern=r"^/cancel$"))
async def handle_cancel(event):
    """Joriy jarayonni bekor qilish"""
    user_id = event.sender_id
    state, _ = db.get_user_state(user_id)
    db.clear_user_state(user_id)
    is_admin = db.is_admin(user_id)
    if state:
        await event.reply("❌ Joriy amal bekor qilindi.", buttons=get_main_keyboard(is_admin))
    else:
        await event.reply("Bekor qilinadigan faol amal yo'q.", buttons=get_main_keyboard(is_admin))


@client.on(events.NewMessage(pattern=r"^/setadmin(?:\s+(.*))?$"))
async def handle_setadmin(event):
    """Admin huquqini olish uchun maxfiy parol buyrug'i"""
    user_id = event.sender_id
    args = (event.pattern_match.group(1) or "").strip()
    if args == Config.ADMIN_SECRET:
        db.set_admin(user_id, True)
        await event.reply(
            "🎉 <b>Tabriklaymiz! Siz muvaffaqiyatli administrator bo'ldingiz!</b>\n\n"
            "Endi menyudagi 👑 <b>Admin Panel</b> tugmasi yoki <code>/admin</code> buyrug'i orqali botni boshqarishingiz mumkin.",
            parse_mode="html",
            buttons=get_main_keyboard(is_admin=True)
        )
    else:
        await event.reply("❌ Noto'g'ri maxfiy parol.")


@client.on(events.NewMessage(pattern=r"^/give(?:\s+(\d+))?(?:\s+(\d+))?$"))
async def handle_give(event):
    """Adminga foydalanuvchiga qo'lda obuna berish imkoniyati"""
    user_id = event.sender_id
    if not db.is_admin(user_id):
        return

    target_id = event.pattern_match.group(1)
    days_str = event.pattern_match.group(2) or "30"

    if not target_id:
        await event.reply("⚠️ Foydalanish: <code>/give &lt;user_id&gt; [kunlar]</code>\nMasalan: <code>/give 12345678 30</code>", parse_mode="html")
        return

    target_id = int(target_id)
    days = int(days_str)
    new_end = db.activate_subscription(target_id, days=days)

    await event.reply(
        f"✅ <b>Foydalanuvchi {target_id} ga {days} kunlik obuna berildi!</b>\n"
        f"📅 Tugash vaqti: <b>{new_end}</b>",
        parse_mode="html"
    )

    try:
        await client.send_message(
            target_id,
            f"🎉 <b>Admin sizga {days} kunlik VIP obuna taqdim etdi!</b>\n\n"
            f"📅 <b>Amal qilish muddati:</b> {new_end} gacha\n"
            "Endi bemalol cheksiz videolaringizga subtitr yaratishingiz mumkin!",
            parse_mode="html",
            buttons=get_main_keyboard(is_admin=False)
        )
    except Exception:
        pass


@client.on(events.NewMessage(pattern=r"^(?:/status|📊 Status|/myid|/id)$"))
async def handle_status_command(event):
    """Hisob holati va limitlarni ko'rsatish"""
    user_id = event.sender_id
    sender = await event.get_sender()
    username = getattr(sender, "username", "") or ""
    first_name = getattr(sender, "first_name", "") or ""
    last_name = getattr(sender, "last_name", "") or ""
    full_name = f"{first_name} {last_name}".strip()

    user = db.get_or_create_user(user_id, username=username, full_name=full_name)
    is_admin = db.is_admin(user_id)
    is_sub = db.is_user_subscribed(user_id)

    if is_admin:
        status_info = "👑 <b>Tarif:</b> Administrator (Cheksiz kirish)"
    elif is_sub:
        sub_end = user.get("subscription_end", "Noma'lum")
        status_info = (
            "💎 <b>Tarif:</b> VIP Oylik Obuna (Faol)\n"
            f"⏳ <b>Amal qilish muddati:</b> {sub_end} gacha\n"
            "🎬 <b>Imkoniyat:</b> Cheksiz subtitrlar"
        )
    else:
        free_uses = user.get("free_uses", 0)
        rem = max(0, Config.FREE_LIMIT - free_uses)
        status_info = (
            "🎁 <b>Tarif:</b> Bepul sinov tarifi\n"
            f"📊 <b>Ishlatilgan videolar:</b> {free_uses} / {Config.FREE_LIMIT} ta\n"
            f"✨ <b>Qolgan bepul videolar:</b> {rem} ta"
        )

    text = (
        "📊 <b>Sizning hisobingiz holati:</b>\n\n"
        f"👤 <b>Foydalanuvchi:</b> {full_name}\n"
        f"🆔 <b>Telegram ID:</b> <code>{user_id}</code>\n"
        f"🔗 <b>Username:</b> @{username or 'mavjud emas'}\n\n"
        f"{status_info}\n\n"
        f"📦 <b>Maksimal hajm:</b> {Config.MAX_FILE_SIZE_MB} MB\n"
        "⚡️ <b>AI Provayder:</b> GROQ (Whisper Large v3)"
    )
    buttons = []
    if not is_sub and not is_admin:
        buttons.append([Button.inline("💎 Oylik obuna sotib olish", b"buy_subscription")])

    await event.reply(text, parse_mode="html", buttons=buttons if buttons else None)


@client.on(events.NewMessage(pattern=r"^(?:/buy|💎 Oylik obuna sotib olish)$"))
async def handle_buy_menu(event):
    """Oylik obuna sotib olish menyusi"""
    text = (
        "💎 <b>Oylik VIP Obuna</b>\n\n"
        "✨ <b>Obuna imkoniyatlari:</b>\n"
        "• 30 kun davomida cheksiz video va audio fayllarga subtitr yaratish\n"
        "• 200 MB gacha katta videolarni qayta ishlash\n"
        "• Aniq va to'g'ri o'zbek adabiy tilida AI imlo tahriri\n"
        "• Subtitrni videoga yopishtirish (Hardsub / Reels)\n"
        "• 1-3 ta so'zdan iborat dinamik chiroyli format\n\n"
        f"💰 <b>Oylik tarif narxi: {Config.SUBSCRIPTION_PRICE:,} so'm</b>".replace(",", " ")
    )
    buttons = [[Button.inline("💳 Sotib olish", b"buy_subscription")]]
    await event.reply(text, parse_mode="html", buttons=buttons)


@client.on(events.CallbackQuery(data=b"buy_subscription"))
async def on_buy_subscription_clicked(event):
    """Foydalanuvchi 'Sotib olish' tugmasini bosganda to'lov rekvizitlari va chek so'rovi"""
    user_id = event.sender_id
    db.set_user_state(user_id, "waiting_receipt")

    text = (
        f"<code>{Config.CARD_NUMBER}</code> {Config.CARD_HOLDER}\n"
        "shu kartaga 15 ming to'lov qilib chek tashlang va\n"
        "admin tasdiqlashini kuting\n\n"
        "<i>(To'lov chekini rasm yoki skrinshot ko'rinishida shu yerga yuboring. Bekor qilish uchun /cancel yozing)</i>"
    )
    buttons = [[Button.inline("❌ Bekor qilish", b"cancel_state")]]
    await event.respond(text, parse_mode="html", buttons=buttons)
    await event.answer()


@client.on(events.NewMessage(pattern=r"^(?:/feedback|✍️ Fikr bildirish)$"))
async def handle_feedback_menu(event):
    """Fikr bildirish bo'limi"""
    user_id = event.sender_id
    db.set_user_state(user_id, "waiting_feedback")

    text = (
        "✍️ <b>Fikr va takliflaringizni yozib qoldiring!</b>\n\n"
        "Bot bo'yicha fikr, savol yoki takliflaringizni bitta xabarda yozib yuboring. "
        "Sizning xabaringiz to'g'ridan-to'g'ri administratorga yetkaziladi.\n\n"
        "<i>(Bekor qilish uchun /cancel deb yozing)</i>"
    )
    buttons = [[Button.inline("❌ Bekor qilish", b"cancel_state")]]
    await event.reply(text, parse_mode="html", buttons=buttons)


@client.on(events.NewMessage(pattern=r"^(?:/admin|/panel|👑 Admin Panel)$"))
async def handle_admin_panel(event):
    """Admin panel menyusi"""
    user_id = event.sender_id
    if not db.is_admin(user_id):
        await event.reply("⛔️ <b>Ushbu bo'lim faqat administratorlar uchun!</b>", parse_mode="html")
        return

    stats = db.get_stats()
    text = (
        "👑 <b>Administrator Paneli</b>\n\n"
        "Kerakli bo'limni tanlang:\n\n"
        f"👥 <b>Jami foydalanuvchilar:</b> {stats['total_users']} ta\n"
        f"💎 <b>VIP obunachilar:</b> {stats['active_subscribers']} ta\n"
        f"⏳ <b>Kutilayotgan to'lovlar:</b> {stats['pending_payments']} ta"
    )
    buttons = [
        [Button.inline("📊 Statistika", b"admin_stats")],
        [Button.inline("📢 Hammaga xabar yuborish", b"admin_broadcast")],
        [Button.inline("💳 Kutilayotgan cheklar", b"admin_pending")],
        [Button.inline("❌ Yopish", b"admin_close")]
    ]
    await event.reply(text, parse_mode="html", buttons=buttons)


# ===================================================================
# ADMIN CALLBACK QUERY HANDLERS
# ===================================================================

@client.on(events.CallbackQuery(data=b"admin_menu"))
async def on_admin_menu(event):
    user_id = event.sender_id
    if not db.is_admin(user_id):
        await event.answer("Ruxsat berilmagan!", alert=True)
        return

    stats = db.get_stats()
    text = (
        "👑 <b>Administrator Paneli</b>\n\n"
        "Kerakli bo'limni tanlang:\n\n"
        f"👥 <b>Jami foydalanuvchilar:</b> {stats['total_users']} ta\n"
        f"💎 <b>VIP obunachilar:</b> {stats['active_subscribers']} ta\n"
        f"⏳ <b>Kutilayotgan to'lovlar:</b> {stats['pending_payments']} ta"
    )
    buttons = [
        [Button.inline("📊 Statistika", b"admin_stats")],
        [Button.inline("📢 Hammaga xabar yuborish", b"admin_broadcast")],
        [Button.inline("💳 Kutilayotgan cheklar", b"admin_pending")],
        [Button.inline("❌ Yopish", b"admin_close")]
    ]
    await event.edit(text, parse_mode="html", buttons=buttons)
    await event.answer()


@client.on(events.CallbackQuery(data=b"admin_stats"))
async def on_admin_stats(event):
    user_id = event.sender_id
    if not db.is_admin(user_id):
        await event.answer("Ruxsat berilmagan!", alert=True)
        return

    stats = db.get_stats()
    text = (
        "📊 <b>Bot To'liq Statistikasi:</b>\n\n"
        f"👥 <b>Jami foydalanuvchilar:</b> {stats['total_users']} ta\n"
        f"💎 <b>Faol VIP obunachilar:</b> {stats['active_subscribers']} ta\n"
        f"🎁 <b>Bepul foydalanuvchilar:</b> {stats['free_users']} ta\n"
        f"⏳ <b>Kutilayotgan cheklar:</b> {stats['pending_payments']} ta\n"
        f"📅 <b>Bugun qo'shilganlar:</b> {stats['today_users']} ta\n\n"
        f"💰 <b>Oylik obuna narxi:</b> {Config.SUBSCRIPTION_PRICE:,} so'm\n"
        f"🎁 <b>Bepul limit:</b> {Config.FREE_LIMIT} ta video".replace(",", " ")
    )
    buttons = [[Button.inline("🔙 Orqaga", b"admin_menu")]]
    await event.edit(text, parse_mode="html", buttons=buttons)
    await event.answer()


@client.on(events.CallbackQuery(data=b"admin_broadcast"))
async def on_admin_broadcast_start(event):
    user_id = event.sender_id
    if not db.is_admin(user_id):
        await event.answer("Ruxsat berilmagan!", alert=True)
        return

    db.set_user_state(user_id, "waiting_broadcast")
    text = (
        "📢 <b>Barcha foydalanuvchilarga xabar yuborish</b>\n\n"
        "Foydalanuvchilarga jo'natmoqchi bo'lgan xabaringizni yuboring.\n"
        "Bu matn, rasm, video yoki audio bo'lishi mumkin.\n\n"
        "<i>(Bekor qilish uchun /cancel deb yozing)</i>"
    )
    buttons = [[Button.inline("❌ Bekor qilish", b"cancel_state")]]
    await event.respond(text, parse_mode="html", buttons=buttons)
    await event.answer()


@client.on(events.CallbackQuery(data=b"admin_pending"))
async def on_admin_pending_check(event):
    user_id = event.sender_id
    if not db.is_admin(user_id):
        await event.answer("Ruxsat berilmagan!", alert=True)
        return

    stats = db.get_stats()
    text = (
        f"💳 <b>Kutilayotgan to'lov cheklari soni:</b> {stats['pending_payments']} ta\n\n"
        "<i>Foydalanuvchilar chek tashlaganida bot ularni to'g'ridan-to'g'ri adminga tasdiqlash tugmalari bilan jo'natadi.</i>"
    )
    buttons = [[Button.inline("🔙 Orqaga", b"admin_menu")]]
    await event.edit(text, parse_mode="html", buttons=buttons)
    await event.answer()


@client.on(events.CallbackQuery(data=b"admin_close"))
async def on_admin_close(event):
    await event.delete()


@client.on(events.CallbackQuery(data=b"cancel_state"))
async def on_cancel_state_callback(event):
    user_id = event.sender_id
    db.clear_user_state(user_id)
    await event.edit("❌ Amal bekor qilindi.", buttons=None)
    await event.answer("Bekor qilindi")


@client.on(events.CallbackQuery(data=re.compile(rb"^pay_ok:(\d+)")))
async def on_payment_approved(event):
    """Admin to'lovni tasdiqlaganda 30 kunlik VIP obuna beriladi"""
    admin_id = event.sender_id
    if not db.is_admin(admin_id):
        await event.answer("⚠️ Faqat adminlar tasdiqlashi mumkin!", alert=True)
        return

    payment_id = int(event.pattern_match.group(1).decode())
    payment = db.get_payment(payment_id)

    if not payment:
        await event.answer("⚠️ To'lov topilmadi.", alert=True)
        return

    if payment["status"] != "pending":
        await event.answer(f"⚠️ Ushbu to'lov allaqachon ko'rib chiqilgan ({payment['status']}).", alert=True)
        return

    target_user_id = payment["user_id"]
    new_end = db.activate_subscription(target_user_id, days=30)
    db.update_payment_status(payment_id, "approved")

    # Admin xabarini yangilash
    await event.edit(
        f"✅ <b>TO'LOV TASDIQLANDI!</b>\n\n"
        f"👤 <b>Foydalanuvchi:</b> {payment['full_name']} (<code>{target_user_id}</code>)\n"
        f"💰 <b>Summa:</b> {payment['amount']:,} so'm\n"
        f"⏳ <b>Berilgan obuna:</b> 30 kun\n"
        f"📅 <b>Tugash vaqti:</b> {new_end}".replace(",", " "),
        parse_mode="html",
        buttons=None
    )
    await event.answer("To'lov tasdiqlandi!")

    # Foydalanuvchiga xushxabar jo'natish
    user_msg = (
        "🎉 <b>Xushxabar! To'lovingiz admin tomonidan tasdiqlandi!</b>\n\n"
        "Sizga <b>30 kunlik VIP cheksiz obuna</b> muvaffaqiyatli faollashtirildi! 🚀\n\n"
        f"📅 <b>Obuna muddati:</b> {new_end} gacha\n\n"
        "Endi botga bemalol xohlagancha video va audio yuborib, o'zbekcha subtitrlar yaratishingiz mumkin!"
    )
    try:
        await client.send_message(
            target_user_id,
            user_msg,
            parse_mode="html",
            buttons=get_main_keyboard(is_admin=False)
        )
    except Exception as e:
        logger.warning(f"Foydalanuvchi {target_user_id} ga xabar yetkazilmadi: {e}")


@client.on(events.CallbackQuery(data=re.compile(rb"^pay_no:(\d+)")))
async def on_payment_rejected(event):
    """Admin to'lovni rad etganda"""
    admin_id = event.sender_id
    if not db.is_admin(admin_id):
        await event.answer("⚠️ Faqat adminlar rad etishi mumkin!", alert=True)
        return

    payment_id = int(event.pattern_match.group(1).decode())
    payment = db.get_payment(payment_id)

    if not payment:
        await event.answer("⚠️ To'lov topilmadi.", alert=True)
        return

    if payment["status"] != "pending":
        await event.answer(f"⚠️ Ushbu to'lov allaqachon ko'rib chiqilgan ({payment['status']}).", alert=True)
        return

    target_user_id = payment["user_id"]
    db.update_payment_status(payment_id, "rejected")

    # Admin xabarini yangilash
    await event.edit(
        f"❌ <b>TO'LOV RAD ETILDI.</b>\n\n"
        f"👤 <b>Foydalanuvchi:</b> {payment['full_name']} (<code>{target_user_id}</code>)\n"
        f"💰 <b>Summa:</b> {payment['amount']:,} so'm".replace(",", " "),
        parse_mode="html",
        buttons=None
    )
    await event.answer("To'lov rad etildi")

    # Foydalanuvchiga xabar
    user_msg = (
        "❌ <b>Kechirasiz, to'lov chekingiz admin tomonidan tasdiqlanmadi.</b>\n\n"
        "Agar to'lovda xatolik yuz bergan bo'lsa yoki savollaringiz bo'lsa, "
        "adminga murojaat qiling yoki qaytadan to'g'ri chekni yuboring."
    )
    try:
        await client.send_message(target_user_id, user_msg, parse_mode="html")
    except Exception:
        pass


# ===================================================================
# MATNLI XABARLAR VA STATE HANDLER
# ===================================================================

@client.on(events.NewMessage)
async def handle_text_and_states(event):
    """Fikr bildirish va Admin Broadcast xabarlarini qabul qilish"""
    # Buyruqlar va media fayllarni o'tkazib yuborish
    if not event.raw_text or event.raw_text.startswith("/"):
        return

    user_id = event.sender_id
    state, state_data = db.get_user_state(user_id)

    # 1. Agar foydalanuvchi fikr yozayotgan bo'lsa
    if state == "waiting_feedback":
        sender = await event.get_sender()
        username = getattr(sender, "username", "") or ""
        first_name = getattr(sender, "first_name", "") or ""
        last_name = getattr(sender, "last_name", "") or ""
        full_name = f"{first_name} {last_name}".strip()

        feedback_text = event.raw_text.strip()
        db.save_feedback(user_id, username, full_name, feedback_text)
        db.clear_user_state(user_id)

        await event.reply("✅ <b>Rahmat! Fikr va taklifingiz administratorga yetkazildi.</b>", parse_mode="html")

        # Barcha adminlarga fikrni jo'natish
        admin_note = (
            "📩 <b>YANGI FIKR / TAKLIF!</b>\n\n"
            f"👤 <b>Kimdan:</b> {full_name}\n"
            f"🆔 <b>User ID:</b> <code>{user_id}</code>\n"
            f"🔗 <b>Username:</b> @{username or 'mavjud emas'}\n\n"
            f"💬 <b>Matn:</b>\n{feedback_text}"
        )
        for adm_id in db.get_all_admins():
            try:
                await client.send_message(adm_id, admin_note, parse_mode="html")
            except Exception as e:
                logger.warning(f"Admin {adm_id} ga fikr yuborishda xato: {e}")
        return

    # 2. Agar admin hammaga xabar yuborayotgan bo'lsa (Broadcast)
    if state == "waiting_broadcast" and db.is_admin(user_id):
        db.clear_user_state(user_id)
        user_ids = db.get_all_user_ids()
        total = len(user_ids)
        status_msg = await event.reply(f"⏳ <b>Xabar {total} ta foydalanuvchiga yuborilmoqda, kuting...</b>", parse_mode="html")

        sent_count = 0
        fail_count = 0

        for uid in user_ids:
            try:
                await client.send_message(uid, event.message.message)
                sent_count += 1
                await asyncio.sleep(0.04)
            except Exception:
                fail_count += 1

        report = (
            "📢 <b>Xabar yuborish yakunlandi!</b>\n\n"
            f"👥 <b>Jami foydalanuvchilar:</b> {total} ta\n"
            f"✅ <b>Muvaffaqiyatli yetkazildi:</b> {sent_count} ta\n"
            f"❌ <b>Yetib bormadi (bloklaganlar):</b> {fail_count} ta"
        )
        await status_msg.edit(report, parse_mode="html")
        return

    # 3. Agar foydalanuvchi chek kutilayotgan paytda matn yozsa
    if state == "waiting_receipt":
        await event.reply(
            "⚠️ <b>Iltimos, to'lov cheki skrinshoti yoki rasmini jo'nating!</b>\n"
            "<i>(Jarayonni bekor qilish uchun /cancel deb yozing)</i>",
            parse_mode="html"
        )
        return


# ===================================================================
# MEDIA (VIDEO / AUDIO / CHEK / BROADCAST MEDIA) QABUL QILISH
# ===================================================================

@client.on(events.NewMessage)
async def handle_incoming_media(event):
    """Media (video / audio / document / rasm) qabul qilish va SRT subtitr yaratish"""
    # Buyruqlarni e'tiborsiz qoldirish
    if event.raw_text and event.raw_text.startswith("/"):
        return

    # Faqat media fayllarni tekshirish
    if not event.media or not event.file:
        return

    user_id = event.sender_id
    sender = await event.get_sender()
    username = getattr(sender, "username", "") or ""
    first_name = getattr(sender, "first_name", "") or ""
    last_name = getattr(sender, "last_name", "") or ""
    full_name = f"{first_name} {last_name}".strip()

    # Foydalanuvchini bazada yangilash
    db.get_or_create_user(user_id, username=username, full_name=full_name)

    state, _ = db.get_user_state(user_id)

    # -------------------------------------------------------------
    # A) CHEKNI QABUL QILISH (Agar holat waiting_receipt bo'lsa)
    # -------------------------------------------------------------
    if state == "waiting_receipt":
        db.clear_user_state(user_id)
        payment_id = db.create_payment(
            user_id=user_id,
            username=username,
            full_name=full_name,
            amount=Config.SUBSCRIPTION_PRICE,
            receipt_message_id=event.id
        )

        await event.reply(
            "✅ <b>To'lov chekingiz qabul qilindi!</b>\n\n"
            "Chek administratorga tekshirish uchun yuborildi. "
            "Admin tasdiqlashi bilan sizga <b>30 kunlik VIP obuna</b> avtomatik faollashtiriladi va bu haqda xabar olasiz.",
            parse_mode="html"
        )

        # Barcha adminlarga chekni jo'natish
        now_str = datetime.now().strftime("%Y-%m-%d %H:%M")
        admin_caption = (
            "🔔 <b>YANGI TO'LOV CHEKI TUSHDI!</b>\n\n"
            f"👤 <b>Foydalanuvchi:</b> {full_name}\n"
            f"🆔 <b>User ID:</b> <code>{user_id}</code>\n"
            f"🔗 <b>Username:</b> @{username or 'mavjud emas'}\n"
            f"💰 <b>Summa:</b> {Config.SUBSCRIPTION_PRICE:,} so'm\n"
            f"📅 <b>Vaqti:</b> {now_str}\n\n"
            "To'lovni tasdiqlaysizmi?".replace(",", " ")
        )
        admin_buttons = [
            [
                Button.inline("✅ Tasdiqlash (30 kun)", f"pay_ok:{payment_id}".encode()),
                Button.inline("❌ Rad etish", f"pay_no:{payment_id}".encode())
            ]
        ]
        for adm_id in db.get_all_admins():
            try:
                await client.send_file(adm_id, event.media, caption=admin_caption, parse_mode="html", buttons=admin_buttons)
            except Exception as e:
                logger.warning(f"Adminga chek yuborishda xato ({adm_id}): {e}")
        return

    # -------------------------------------------------------------
    # B) ADMIN BROADCAST MEDIA (Agar admin rasm/video jo'natsa)
    # -------------------------------------------------------------
    if state == "waiting_broadcast" and db.is_admin(user_id):
        db.clear_user_state(user_id)
        user_ids = db.get_all_user_ids()
        total = len(user_ids)
        status_msg = await event.reply(f"⏳ <b>Media xabar {total} ta foydalanuvchiga yuborilmoqda...</b>", parse_mode="html")

        sent_count = 0
        fail_count = 0

        for uid in user_ids:
            try:
                await client.send_file(uid, event.media, caption=event.message.message)
                sent_count += 1
                await asyncio.sleep(0.04)
            except Exception:
                fail_count += 1

        report = (
            "📢 <b>Xabar yuborish yakunlandi!</b>\n\n"
            f"👥 <b>Jami foydalanuvchilar:</b> {total} ta\n"
            f"✅ <b>Yetkazildi:</b> {sent_count} ta\n"
            f"❌ <b>Yetib bormadi (bloklaganlar):</b> {fail_count} ta"
        )
        await status_msg.edit(report, parse_mode="html")
        return

    # -------------------------------------------------------------
    # C) VIDEO VA AUDIO UCHUN LIMITLARNI TEKSHIRISH
    # -------------------------------------------------------------
    can_process, reason, remaining = db.can_process_media(user_id)

    if not can_process:
        limit_text = (
            "⚠️ <b>Bepul limit tugadi!</b>\n\n"
            f"Siz yangi foydalanuvchilar uchun ajratilgan <b>{Config.FREE_LIMIT} ta bepul</b> subtitr yaratish limitidan foydalanib bo'ldingiz.\n\n"
            "Botdan cheksiz foydalanishni davom ettirish uchun <b>oylik obuna (15 000 so'm)</b> xarid qiling!"
        )
        buttons = [[Button.inline("💎 Oylik obuna sotib olish (15 000 so'm)", b"buy_subscription")]]
        await event.reply(limit_text, parse_mode="html", buttons=buttons)
        return

    file_size = event.file.size or 0

    # Aniq media turini aniqlash (voice / audio / video)
    media_type = None
    is_video = False
    ext = ".mp4"
    file_name = "fayl.mp4"

    if event.voice:
        media_type = "voice"
        is_video = False
        ext = event.file.ext or ".ogg"
        file_name = event.file.name or "ovozli_xabar.ogg"
    elif event.audio:
        media_type = "audio"
        is_video = False
        ext = event.file.ext or ".mp3"
        file_name = event.file.name or "audio.mp3"
    elif event.video:
        media_type = "video"
        is_video = True
        ext = event.file.ext or ".mp4"
        file_name = event.file.name or "video.mp4"
    elif event.document:
        mime = getattr(event.document, "mime_type", "") or ""
        raw_name = event.file.name or ""
        raw_ext = (event.file.ext or Path(raw_name).suffix or "").lower()

        if mime.startswith("audio/") or raw_ext in AUDIO_EXTENSIONS:
            media_type = "audio"
            is_video = False
            ext = raw_ext if raw_ext in AUDIO_EXTENSIONS else ".mp3"
            file_name = raw_name or "audio.mp3"
        elif mime.startswith("video/") or raw_ext in VIDEO_EXTENSIONS:
            media_type = "video"
            is_video = True
            ext = raw_ext if raw_ext in VIDEO_EXTENSIONS else ".mp4"
            file_name = raw_name or "video.mp4"
        else:
            return
    else:
        return

    media_names = {
        "voice": "Ovozli xabar",
        "audio": "Audio fayl",
        "video": "Video"
    }
    media_label = media_names.get(media_type, "Fayl")

    # 1. Hajm chegarasini tekshirish
    max_bytes = Config.MAX_FILE_SIZE_MB * 1024 * 1024
    if file_size > max_bytes:
        size_mb = round(file_size / (1024 * 1024), 1)
        await event.reply(
            f"⚠️ <b>Kechirasiz, fayl hajmi juda katta ({size_mb} MB)!</b>\n\n"
            f"Bot maksimal <b>{Config.MAX_FILE_SIZE_MB} MB</b> gacha bo'lgan fayllarni qabul qiladi.",
            parse_mode="html"
        )
        return

    # 2. Jarayon xabari
    status_msg = await event.reply(
        f"⏳ <b>{media_label} qabul qilindi. Jarayon boshlanmoqda...</b>",
        parse_mode="html"
    )

    # 3. Vaqtinchalik papka
    job_id = uuid.uuid4().hex[:10]
    job_dir = Config.TEMP_DIR / job_id
    job_dir.mkdir(parents=True, exist_ok=True)

    input_file_path = job_dir / f"input{ext}"
    audio_path = job_dir / "audio.mp3"
    srt_path = job_dir / f"{Path(file_name).stem}_subtitr.srt"

    last_pct = [0]
    last_update = [0.0]

    async def download_progress(current, total):
        now = time.time()
        pct = int(current * 100 / total)
        if (pct - last_pct[0] >= 5 or now - last_update[0] >= 3.0) and pct < 100:
            last_pct[0] = pct
            last_update[0] = now
            cur_mb = round(current / (1024 * 1024), 1)
            tot_mb = round(total / (1024 * 1024), 1)
            try:
                await status_msg.edit(
                    f"📥 <b>{media_label} yuklab olinmoqda:</b> {pct}% ({cur_mb} MB / {tot_mb} MB)...",
                    parse_mode="html"
                )
            except Exception:
                pass

    try:
        # Faylni yuklab olish
        await event.download_media(file=input_file_path, progress_callback=download_progress)

        # 4. Audioni optimizatsiya qilish (FFmpeg)
        action_text = "Videodan audio ajratilmoqda" if is_video else "Audio optimizatsiya qilinmoqda"
        await status_msg.edit(f"🎵 <b>1/3: {action_text} (FFmpeg)...</b>", parse_mode="html")
        await FFmpegService.extract_audio(input_file_path, audio_path)

        # Davomiylikni aniqlash
        duration = await FFmpegService.get_video_duration(audio_path)
        formatted_duration = SRTHelper.format_duration(duration)

        # 5. AI orqali SRT generatsiya va imlo tekshiruvi
        await status_msg.edit(
            "🧠 <b>2/3: AI nutqni tahlil qilib, imlo va grammatikani to'g'rilamoqda...</b>\n"
            "<i>Iltimos, kuting (so'zlar 1-3 tadan qilib aniq chiqariladi)...</i>",
            parse_mode="html"
        )
        srt_content = await subtitle_service.transcribe(audio_path, language=Config.SUBTITLE_LANGUAGE)

        # 6. SRT faylini saqlash
        await status_msg.edit("📝 <b>3/3: Subtitr fayli shakllantirilmoqda...</b>", parse_mode="html")
        with open(srt_path, "w", encoding="utf-8") as f:
            f.write(srt_content)

        # Statistika
        cues_count = SRTHelper.count_srt_cues(srt_content)
        preview_text = SRTHelper.get_srt_preview(srt_content, max_items=5)

        caption = (
            f"✅ <b>{media_label} uchun o'zbekcha subtitr (.srt) tayyor bo'ldi!</b>\n\n"
            f"⏱ <b>Davomiyligi:</b> {formatted_duration}\n"
            f"📊 <b>Subtitr qatorlari:</b> {cues_count} ta (1-3 so'zdan)\n\n"
            f"📝 <b>Matndan parcha:</b>\n{preview_text}\n\n"
            "💡 <i>Ushbu .srt faylni CapCut, Premiere Pro, DaVinci Resolve yoki pleyerlarga to'g'ridan-to'g'ri yuklashingiz mumkin.</i>"
        )

        buttons = build_job_buttons(job_id, is_video=is_video)

        # 7. SRT faylni yuborish
        await event.reply(
            file=str(srt_path),
            message=caption,
            parse_mode="html",
            buttons=buttons
        )

        await status_msg.edit(f"✨ <b>{media_label} subtitri muvaffaqiyatli tayyorlandi va yuborildi!</b>", parse_mode="html")

        # ---------------------------------------------------------
        # Bepul limitni yangilash va foydalanuvchiga eslatish
        # ---------------------------------------------------------
        if reason == "free":
            new_used = db.increment_free_uses(user_id)
            new_rem = max(0, Config.FREE_LIMIT - new_used)
            if new_rem > 0:
                await event.respond(
                    f"🎁 <i>Sizda qolgan bepul urinishlar soni: <b>{new_rem} ta</b> (Jami {Config.FREE_LIMIT} tadan {new_used} tasi ishlatildi).</i>",
                    parse_mode="html"
                )
            else:
                await event.respond(
                    "⚠️ <i>Bu sizning oxirgi (4-chi) bepul videongiz edi! Keyingi videolaringiz uchun oylik obuna (15 000 so'm) xarid qilishingiz mumkin.</i>",
                    parse_mode="html",
                    buttons=[[Button.inline("💎 Oylik obuna sotib olish", b"buy_subscription")]]
                )

    except Exception as e:
        logger.exception("Media tahrirlashda xatolik:")
        await status_msg.edit(
            f"❌ <b>Xatolik yuz berdi:</b>\n<code>{str(e)[:400]}</code>\n\n"
            "💡 Iltimos, ovoz tiniqligini tekshirib qaytadan urinib ko'ring.",
            parse_mode="html"
        )


# ===================================================================
# HARDSUB, TXT VA TARJIMA CALLBACKS
# ===================================================================

@client.on(events.CallbackQuery(data=re.compile(b"^hardsub:(.*)")))
async def on_hardsub_clicked(event):
    """Subtitrni videoga yopishtirish yoki audiodan subtitrli video yaratish"""
    job_id = event.data.decode().split(":")[1]
    job_dir = Config.TEMP_DIR / job_id

    if not job_dir.exists():
        await event.answer("⚠️ Fayl muddati o'tgan. Iltimos, faylni qayta yuboring.", alert=True)
        return

    input_files = list(job_dir.glob("input.*"))
    srt_files = list(job_dir.glob("*.srt"))

    if not input_files or not srt_files:
        await event.answer("⚠️ Fayllar topilmadi.", alert=True)
        return

    input_path = input_files[0]
    srt_path = srt_files[0]
    output_video_path = job_dir / "subtitrli_video.mp4"
    ext = input_path.suffix.lower()
    is_video = ext in VIDEO_EXTENSIONS

    await event.answer()
    progress_text = (
        "🎬 <b>Subtitr videoga yopishtirilmoqda (Hardsub)...</b>\n<i>Bu jarayon video hajmiga qarab 15-60 soniya vaqt olishi mumkin. Kuting...</i>"
        if is_video else
        "🎬 <b>Ovozli xabardan subtitrli video yaratilmoqda...</b>\n<i>Iltimos, biroz kuting...</i>"
    )
    progress_msg = await event.reply(progress_text, parse_mode="html")

    try:
        if is_video:
            await FFmpegService.burn_subtitles(input_path, srt_path, output_video_path)
        else:
            await FFmpegService.audio_to_subtitled_video(input_path, srt_path, output_video_path)

        caption = (
            "🎬 <b>Subtitrli video muvaffaqiyatli tayyorlandi!</b>\n\n"
            "✨ Endi uni to'g'ridan-to'g'ri tomosha qilishingiz yoki ijtimoiy tarmoqlarga (Reels / Shorts) yuklashingiz mumkin."
        )

        await event.reply(
            file=str(output_video_path),
            message=caption,
            parse_mode="html",
            supports_streaming=True
        )
        await progress_msg.delete()

    except Exception as e:
        logger.exception("Video yaratishda xatolik:")
        await progress_msg.edit(
            f"❌ <b>Video yaratishda xatolik:</b>\n<code>{str(e)[:300]}</code>",
            parse_mode="html"
        )


@client.on(events.CallbackQuery(data=re.compile(b"^txt:(.*)")))
async def on_txt_clicked(event):
    """Subtitrni sof matn (.txt) sifatida yuborish"""
    job_id = event.data.decode().split(":")[1]
    job_dir = Config.TEMP_DIR / job_id

    if not job_dir.exists():
        await event.answer("⚠️ Fayl muddati o'tgan. Iltimos, videoni qayta yuboring.", alert=True)
        return

    srt_files = list(job_dir.glob("*.srt"))
    if not srt_files:
        await event.answer("⚠️ SRT fayli topilmadi.", alert=True)
        return

    srt_path = srt_files[0]
    txt_path = job_dir / f"{srt_path.stem}_matn.txt"

    try:
        with open(srt_path, "r", encoding="utf-8") as f:
            srt_content = f.read()

        plain_text = SRTHelper.srt_to_plain_text(srt_content)
        with open(txt_path, "w", encoding="utf-8") as f:
            f.write(plain_text)

        await event.answer()
        await event.reply(
            file=str(txt_path),
            message="📄 <b>Audioning to'liq matni (.txt transkripsiya)</b>",
            parse_mode="html"
        )
    except Exception as e:
        logger.exception("Matn ajratishda xatolik:")
        await event.answer(f"Xatolik: {e}", alert=True)


@client.on(events.CallbackQuery(data=re.compile(b"^trans:(.*):(.*)")))
async def on_translate_clicked(event):
    """Subtitrni boshqa tilga (ru / en) tarjima qilish"""
    parts = event.data.decode().split(":")
    job_id = parts[1]
    target_lang = parts[2]

    job_dir = Config.TEMP_DIR / job_id
    if not job_dir.exists():
        await event.answer("⚠️ Fayl muddati o'tgan. Iltimos, videoni qayta yuboring.", alert=True)
        return

    srt_files = list(job_dir.glob("*_subtitr.srt")) or list(job_dir.glob("*.srt"))
    if not srt_files:
        await event.answer("⚠️ SRT fayli topilmadi.", alert=True)
        return

    srt_path = srt_files[0]
    lang_name = "Ruscha" if target_lang == "ru" else "Inglizcha"
    output_srt_path = job_dir / f"{srt_path.stem}_{target_lang}.srt"

    await event.answer()
    progress_msg = await event.reply(
        f"🌐 <b>Subtitr {lang_name} tiliga tarjima qilinmoqda...</b>\n"
        "<i>Vaqt belgilari (timestamps) to'liq saqlanadi. Kuting...</i>",
        parse_mode="html"
    )

    try:
        with open(srt_path, "r", encoding="utf-8") as f:
            srt_content = f.read()

        translated_srt = await subtitle_service.translate_srt(srt_content, target_lang=target_lang)
        with open(output_srt_path, "w", encoding="utf-8") as f:
            f.write(translated_srt)

        preview = SRTHelper.get_srt_preview(translated_srt, max_items=4)
        caption = (
            f"🌐 <b>{lang_name} tilidagi subtitr (.srt) tayyor!</b>\n\n"
            f"📝 <b>Parcha:</b>\n{preview}"
        )

        await event.reply(
            file=str(output_srt_path),
            message=caption,
            parse_mode="html"
        )
        await progress_msg.delete()

    except Exception as e:
        logger.exception("Tarjima qilishda xatolik:")
        await progress_msg.edit(
            f"❌ <b>Tarjima qilishda xatolik:</b>\n<code>{str(e)[:300]}</code>",
            parse_mode="html"
        )


async def start_health_server():
    """Hugging Face Spaces, Render va boshqa bulutli hostinglar uchun HTTP healthcheck serveri (Port 7860)"""
    port = int(os.getenv("PORT", "7860"))

    async def handle_http(reader, writer):
        try:
            await reader.read(1024)
            html = (
                "<!DOCTYPE html><html><head><meta charset='utf-8'><title>QuicSub Bot</title></head>"
                "<body style='font-family:sans-serif;text-align:center;padding:50px;background:#0f172a;color:#f8fafc;'>"
                "<h1>🎬 QuicSub Telegram Bot</h1>"
                "<p style='color:#22c55e;font-size:20px;font-weight:bold;'>● Holat: Faol va ishlamoqda (Online)</p>"
                "<p>Telegram: @quicsub_bot</p>"
                "</body></html>"
            )
            body = html.encode("utf-8")
            response = (
                f"HTTP/1.1 200 OK\r\n"
                f"Content-Type: text/html; charset=utf-8\r\n"
                f"Content-Length: {len(body)}\r\n"
                f"Connection: close\r\n\r\n"
            ).encode("utf-8") + body
            writer.write(response)
            await writer.drain()
        except Exception:
            pass
        finally:
            try:
                writer.close()
            except Exception:
                pass

    try:
        server = await asyncio.start_server(handle_http, "0.0.0.0", port)
        logger.info(f"Healthcheck HTTP server faol: http://0.0.0.0:{port}")
    except Exception as e:
        logger.warning(f"Healthcheck serverida ogohlantirish: {e}")


async def periodic_temp_cleaner():
    """Har 30 daqiqada 1 soatdan eski vaqtinchalik fayllarni tozalash"""
    while True:
        try:
            await asyncio.sleep(1800)
            Cleaner.cleanup_old_temp(Config.TEMP_DIR, max_age_seconds=3600)
        except asyncio.CancelledError:
            break
        except Exception as e:
            logger.warning(f"Tozalashda xatolik: {e}")


async def main():
    valid, message = Config.validate()
    if not valid:
        logger.error(f"❌ Sozlamalarda xatolik: {message}")
        print(f"\nXatolik: {message}\n")
        return

    logger.info(f"✅ Konfiguratsiya muvaffaqiyatli tekshirildi: {message}")

    # Telethon orqali bot sifatida ulanish
    await client.start(bot_token=Config.BOT_TOKEN)
    bot_info = await client.get_me()
    provider_name = Config.get_active_provider().upper()

    logger.info(f"Bot nomi: {bot_info.first_name} (@{bot_info.username})")
    logger.info(f"AI Provayder: {provider_name} (Whisper Large v3)")
    logger.info(f"Maksimal hajm: {Config.MAX_FILE_SIZE_MB} MB (MTProto)")
    logger.info(f"Karta: {Config.CARD_NUMBER} ({Config.CARD_HOLDER}), Narxi: {Config.SUBSCRIPTION_PRICE}")

    print("\n" + "=" * 65, flush=True)
    print("      🎬 O'ZBEKCHA SUBTITR (.SRT) BOTI ISHGA TUSHDI", flush=True)
    print("=" * 65, flush=True)
    print(f"  • Bot nomi      : {bot_info.first_name} (@{bot_info.username})", flush=True)
    print(f"  • AI Provayder  : {provider_name} (Whisper Large v3)", flush=True)
    print(f"  • Asosiy til    : {Config.SUBTITLE_LANGUAGE.upper()} (O'zbekcha)", flush=True)
    print(f"  • Maksimal hajm : {Config.MAX_FILE_SIZE_MB} MB (MTProto)", flush=True)
    print(f"  • Bepul limit   : {Config.FREE_LIMIT} ta video", flush=True)
    print(f"  • Oylik narx    : {Config.SUBSCRIPTION_PRICE:,} so'm".replace(",", " "), flush=True)
    print("=" * 65, flush=True)
    print("Bot 200 MB gacha videolarni qabul qilishga tayyor!\n", flush=True)

    cleaner_task = asyncio.create_task(periodic_temp_cleaner())
    asyncio.create_task(start_health_server())

    try:
        await client.run_until_disconnected()
    finally:
        cleaner_task.cancel()
        logger.info("Bot to'xtatildi.")


_lock_socket = None

def acquire_instance_lock(port: int = 58291):
    """
    Faqat bitta bot nusxasi ishlashini ta'minlovchi port qulfi.
    Agar bot allaqachon fonda ishlab turgan bo'lsa, xabarlar ko'payib (dublikat) ketishining oldini oladi.
    """
    global _lock_socket
    port_env = os.getenv("BOT_LOCK_PORT", str(port))
    if port_env == "0":
        return
    try:
        lock_port = int(port_env)
        _lock_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        _lock_socket.bind(("127.0.0.1", lock_port))
    except socket.error:
        print(f"\n[XATOLIK] Bot allaqachon orqa fonda ishlab turibdi! (Port {port_env} band)")
        logger.error(f"Bot allaqachon ishlamoqda. Dublikat nusxa to'xtatildi.")
        sys.exit(0)


if __name__ == "__main__":
    acquire_instance_lock()
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        print("\nBot to'xtatildi.")
