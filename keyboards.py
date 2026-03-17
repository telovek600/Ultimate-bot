from aiogram.types import (
    ReplyKeyboardMarkup, KeyboardButton,
    InlineKeyboardMarkup, InlineKeyboardButton,
)
 
 
# ── Главное меню ───────────────────────────────────────────
 
def main_keyboard(is_admin: bool = False):
    kb = [
        [KeyboardButton(text="✂️ Записаться")],
        [KeyboardButton(text="💈 Услуги и цены"), KeyboardButton(text="📍 Адрес")],
        [KeyboardButton(text="👨‍🔧 Специалисты"),  KeyboardButton(text="❌ Отменить запись")],
        [KeyboardButton(text="🎁 Мои бонусы")],
    ]
    if is_admin:
        kb.append([KeyboardButton(text="🛠 Админ-панель")])
    return ReplyKeyboardMarkup(keyboard=kb, resize_keyboard=True)
 
 
# ── Запись ─────────────────────────────────────────────────
 
def phone_keyboard():
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="📱 Отправить номер", request_contact=True)],
            [KeyboardButton(text="⬅️ Назад")],
        ],
        resize_keyboard=True, one_time_keyboard=True,
    )
 
 
def barbers_keyboard(barbers: list):
    kb = [[KeyboardButton(text=b)] for b in barbers]
    kb.append([KeyboardButton(text="⬅️ Назад")])
    return ReplyKeyboardMarkup(keyboard=kb, resize_keyboard=True)
 
 
def services_keyboard(services: list):
    kb = [[KeyboardButton(text=s)] for s in services]
    kb.append([KeyboardButton(text="⬅️ Назад")])
    return ReplyKeyboardMarkup(keyboard=kb, resize_keyboard=True)
 
 
def dates_keyboard(dates: list):
    kb = [[KeyboardButton(text=d)] for d in dates]
    kb.append([KeyboardButton(text="⬅️ Назад")])
    return ReplyKeyboardMarkup(keyboard=kb, resize_keyboard=True)
 
 
def times_keyboard(times: list):
    kb = [[KeyboardButton(text=t)] for t in times]
    kb.append([KeyboardButton(text="⬅️ Назад")])
    return ReplyKeyboardMarkup(keyboard=kb, resize_keyboard=True)
 
 
def use_bonuses_keyboard(balance: int, max_spend: int):
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text=f"✅ Да, списать {max_spend} бонусов")],
            [KeyboardButton(text="❌ Нет, оплатить полностью")],
        ],
        resize_keyboard=True,
    )
 
 
# ── Специалисты ────────────────────────────────────────────
 
def specialists_keyboard(barbers: list):
    kb = [
        [InlineKeyboardButton(text=b, callback_data=f"show_barber:{b}")]
        for b in barbers
    ]
    return InlineKeyboardMarkup(inline_keyboard=kb)
 
 
# ── Отмена записи (клиент) ─────────────────────────────────
 
def cancel_bookings_keyboard(bookings: list):
    kb = []
    for b in bookings:
        kb.append([InlineKeyboardButton(
            text=f"❌ {b['booking_date']} {b['booking_time']} — {b['barber']} ({b['service']})",
            callback_data=f"cancel_booking:{b['id']}"
        )])
    kb.append([InlineKeyboardButton(text="🔙 Закрыть", callback_data="cancel_booking:close")])
    return InlineKeyboardMarkup(inline_keyboard=kb)
 
 
def confirm_cancel_keyboard(booking_id: int):
    return InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="✅ Да, отменить",  callback_data=f"confirm_cancel:{booking_id}"),
        InlineKeyboardButton(text="🔙 Нет, назад",    callback_data="cancel_booking:back"),
    ]])
 
 
# ── Отмена записи (админ) ──────────────────────────────────
 
def admin_cancel_bookings_keyboard(bookings: list):
    kb = []
    for b in bookings:
        kb.append([InlineKeyboardButton(
            text=f"🗑 #{b['id']} {b['booking_date']} {b['booking_time']} — {b['client_name']} | {b['barber']}",
            callback_data=f"admin_cancel:{b['id']}"
        )])
    kb.append([InlineKeyboardButton(text="🔙 Закрыть", callback_data="admin_cancel:close")])
    return InlineKeyboardMarkup(inline_keyboard=kb)
 
 
def admin_confirm_cancel_keyboard(booking_id: int):
    return InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="✅ Отменить запись",   callback_data=f"admin_confirm_cancel:{booking_id}"),
        InlineKeyboardButton(text="🔙 Назад к списку",   callback_data="admin_cancel:back"),
    ]])
 
 
# ── Админ-панель ───────────────────────────────────────────
 
def admin_keyboard():
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="📅 Записи на сегодня")],
            [KeyboardButton(text="📚 Последние записи"),  KeyboardButton(text="📖 История записей")],
            [KeyboardButton(text="📊 Статистика")],
            [KeyboardButton(text="🗑 Отменить запись (админ)")],
            [KeyboardButton(text="👨‍🔧 Управление барберами")],
            [KeyboardButton(text="🎁 Программа лояльности")],
            [KeyboardButton(text="📢 Рассылка клиентам")],
            [KeyboardButton(text="📤 Выгрузить в Google Sheets")],
            [KeyboardButton(text="🏠 В меню")],
        ],
        resize_keyboard=True,
    )
 
 
# ── Статистика — выбор периода ─────────────────────────────
 
def stats_period_keyboard():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📅 Сегодня",    callback_data="stats:today")],
        [InlineKeyboardButton(text="📅 Эта неделя", callback_data="stats:week")],
        [InlineKeyboardButton(text="📅 Этот месяц", callback_data="stats:month")],
        [InlineKeyboardButton(text="📅 Все время",  callback_data="stats:all")],
    ])
 
 
# ── Программа лояльности (админ) ──────────────────────────
 
def loyalty_admin_keyboard(cashback_on: bool, visits_on: bool):
    cb_icon = "✅" if cashback_on else "❌"
    vi_icon = "✅" if visits_on  else "❌"
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(
            text=f"{cb_icon} Кэшбэк % от суммы",
            callback_data="loyalty_toggle:cashback"
        )],
        [InlineKeyboardButton(
            text=f"{vi_icon} Фиксированные баллы за визит",
            callback_data="loyalty_toggle:visits"
        )],
        [InlineKeyboardButton(text="🔙 Назад", callback_data="loyalty_toggle:close")],
    ])
 
 
# ── Рассылка ───────────────────────────────────────────────
 
def broadcast_keyboard():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📤 Отправить сейчас",           callback_data="broadcast:now")],
        [InlineKeyboardButton(text="🕐 Запланировать рассылку",      callback_data="broadcast:schedule")],
        [InlineKeyboardButton(text="📋 Запланированные рассылки",    callback_data="broadcast:pending")],
        [InlineKeyboardButton(text="📖 История рассылок",            callback_data="broadcast:history")],
        [InlineKeyboardButton(text="🔙 Назад",                       callback_data="broadcast:close")],
    ])
 
 
def broadcast_confirm_keyboard():
    return InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="✅ Отправить",  callback_data="broadcast_confirm:yes"),
        InlineKeyboardButton(text="❌ Отмена",     callback_data="broadcast_confirm:no"),
    ]])
 
 
def scheduled_broadcasts_keyboard(broadcasts: list):
    """Список запланированных рассылок с кнопкой отмены каждой."""
    kb = []
    for bc in broadcasts:
        dt = (bc["scheduled_at"] or "")[:16].replace("T", " ")
        preview = (bc["text"] or "")[:30] + ("..." if len(bc["text"] or "") > 30 else "")
        kb.append([InlineKeyboardButton(
            text=f"🕐 {dt} — {preview}",
            callback_data=f"broadcast_cancel_view:{bc['id']}"
        )])
    kb.append([InlineKeyboardButton(text="🔙 Назад", callback_data="broadcast:close")])
    return InlineKeyboardMarkup(inline_keyboard=kb)
 
 
def broadcast_cancel_confirm_keyboard(broadcast_id: int):
    return InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="🗑 Да, отменить рассылку", callback_data=f"broadcast_cancel_confirm:{broadcast_id}"),
        InlineKeyboardButton(text="🔙 Назад",                 callback_data="broadcast_cancel_back"),
    ]])
 
