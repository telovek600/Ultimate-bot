from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from typing import Optional
 
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from aiogram import Bot
 
from config import TIMEZONE, REMINDER_HOURS_BEFORE
from database import (
    get_future_unreminded_bookings,
    mark_booking_reminded,
    archive_expired_bookings,
    get_pending_broadcasts,
    mark_broadcast_sent,
    get_all_clients,
    get_clients_not_visited_since,
    get_setting,
)
 
scheduler = AsyncIOScheduler(timezone=TIMEZONE)
_bot: Optional[Bot] = None
 
 
def set_bot(bot: Bot):
    global _bot
    _bot = bot
 
 
# ── Напоминание о записи ───────────────────────────────────
 
async def send_booking_reminder(booking_id, user_id, barber,
                                service, booking_date, booking_time):
    if not _bot:
        return
    try:
        await _bot.send_message(
            user_id,
            "⏰ <b>Напоминание о записи</b>\n\n"
            f"💈 Мастер: {barber}\n"
            f"✂️ Услуга: {service}\n"
            f"📅 Дата: {booking_date}\n"
            f"🕒 Время: {booking_time}\n\n"
            "Ждём вас в барбершопе! 💈",
            parse_mode="HTML",
        )
        mark_booking_reminded(booking_id)
    except Exception:
        pass
 
 
def schedule_booking_reminder(booking_id, user_id, barber,
                               service, booking_date, booking_time, appointment_at):
    appointment_dt = datetime.fromisoformat(appointment_at)
    reminder_dt = appointment_dt - timedelta(hours=REMINDER_HOURS_BEFORE)
    now = datetime.now(ZoneInfo(TIMEZONE)).replace(tzinfo=None)
    if reminder_dt <= now:
        return
    scheduler.add_job(
        send_booking_reminder,
        trigger="date",
        run_date=reminder_dt,
        id=f"reminder_{booking_id}",
        replace_existing=True,
        kwargs=dict(booking_id=booking_id, user_id=user_id, barber=barber,
                    service=service, booking_date=booking_date, booking_time=booking_time),
    )
 
 
# ── Архивация просроченных записей (каждые 5 мин) ─────────
 
async def job_archive_expired():
    archive_expired_bookings()
 
 
# ── Запланированные рассылки (каждую минуту) ──────────────
 
async def job_send_pending_broadcasts():
    if not _bot:
        return
    now_iso = datetime.now(ZoneInfo(TIMEZONE)).strftime("%Y-%m-%dT%H:%M:%S")
    broadcasts = get_pending_broadcasts(now_iso)
    for bc in broadcasts:
        clients = get_all_clients()
        sent, failed = 0, 0
        for c in clients:
            try:
                await _bot.send_message(c["user_id"], bc["text"])
                sent += 1
            except Exception:
                failed += 1
        mark_broadcast_sent(bc["id"], sent, failed)
 
 
# ── Рассылка по расписанию (еженедельно/ежедневно) ────────
 
async def job_scheduled_broadcast():
    """
    Читает настройки из БД и отправляет рассылку
    если сегодня нужный день и время совпадает.
    """
    if not _bot:
        return
    if get_setting("broadcast_schedule_enabled") != "1":
        return
 
    text = get_setting("broadcast_schedule_text") or ""
    if not text:
        return
 
    schedule_day  = get_setting("broadcast_schedule_day")   # "0"-"6" или "every"
    schedule_time = get_setting("broadcast_schedule_time")  # "HH:MM"
 
    now = datetime.now(ZoneInfo(TIMEZONE))
    now_time = now.strftime("%H:%M")
 
    if schedule_day != "every" and str(now.weekday()) != schedule_day:
        return
    if now_time != schedule_time:
        return
 
    clients = get_all_clients()
    sent, failed = 0, 0
    for c in clients:
        try:
            await _bot.send_message(c["user_id"], text)
            sent += 1
        except Exception:
            failed += 1
 
    from database import create_broadcast, mark_broadcast_sent
    bc_id = create_broadcast(text)
    mark_broadcast_sent(bc_id, sent, failed)
 
 
# ── Win-back: клиенты, не приходившие 30 дней ─────────────
 
async def job_winback():
    """Раз в день отправляет сообщение клиентам, которые не были 30 дней."""
    if not _bot:
        return
    cutoff = (datetime.now() - timedelta(days=30)).isoformat(timespec="seconds")
    clients = get_clients_not_visited_since(cutoff)
    for c in clients:
        try:
            await _bot.send_message(
                c["user_id"],
                "👋 Давно не виделись!\n\n"
                "Скучаем по вам. Запишитесь прямо сейчас — нажмите ✂️ Записаться 💈",
            )
        except Exception:
            pass
 
 
# ── Загрузка напоминаний + регистрация джобов ─────────────
 
def load_reminders_from_db():
    now_iso = datetime.now().isoformat(timespec="seconds")
    for row in get_future_unreminded_bookings(now_iso):
        schedule_booking_reminder(
            booking_id=row["id"],
            user_id=row["user_id"],
            barber=row["barber"],
            service=row["service"],
            booking_date=row["booking_date"],
            booking_time=row["booking_time"],
            appointment_at=row["appointment_at"],
        )
 
    if not scheduler.get_job("archive_expired"):
        scheduler.add_job(job_archive_expired, "interval", minutes=5,
                          id="archive_expired", replace_existing=True)
 
    if not scheduler.get_job("pending_broadcasts"):
        scheduler.add_job(job_send_pending_broadcasts, "interval", minutes=1,
                          id="pending_broadcasts", replace_existing=True)
 
    if not scheduler.get_job("scheduled_broadcast"):
        scheduler.add_job(job_scheduled_broadcast, "interval", minutes=1,
                          id="scheduled_broadcast", replace_existing=True)
 
    if not scheduler.get_job("winback"):
        scheduler.add_job(job_winback, "cron", hour=10, minute=0,
                          id="winback", replace_existing=True)
