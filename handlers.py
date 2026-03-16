import re
from datetime import datetime, timedelta

from aiogram import Router, F
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import Message, CallbackQuery

from config import (
    ADMIN_IDS, BARBERSHOP_NAME, ADDRESS, CONTACTS,
    SERVICES, BOOKING_DAYS_AHEAD, TIME_SLOT_STEP_MINUTES,
    CASHBACK_PERCENT, VISITS_BONUS_AMOUNT, MAX_BONUS_SPEND_PCT,
)
from database import (
    get_barbers, get_barber, get_barber_names, add_barber, delete_barber,
    upsert_client, get_client, create_booking,
    get_bookings_for_barber_date, get_today_bookings, get_recent_bookings,
    get_all_clients, get_active_bookings_for_user, get_all_active_bookings,
    get_booking_by_id, cancel_booking, get_booking_history,
    get_bonus_balance, add_bonuses, spend_bonuses, get_bonus_log,
    get_setting, set_setting,
    get_stats, create_broadcast, get_broadcast_history, mark_broadcast_sent,
)
from keyboards import (
    main_keyboard, phone_keyboard, barbers_keyboard, services_keyboard,
    dates_keyboard, times_keyboard, use_bonuses_keyboard,
    admin_keyboard, specialists_keyboard,
    cancel_bookings_keyboard, confirm_cancel_keyboard,
    admin_cancel_bookings_keyboard, admin_confirm_cancel_keyboard,
    stats_period_keyboard, loyalty_admin_keyboard,
    broadcast_keyboard, broadcast_confirm_keyboard,
)
from scheduler_jobs import schedule_booking_reminder
from states import BookingState, AdminState, BarberAdminState

router = Router()


# ── Utils ──────────────────────────────────────────────────

def is_admin(user_id: int) -> bool:
    return user_id in ADMIN_IDS


def format_date_label(d: datetime) -> str:
    days = ["Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс"]
    return f"{d.strftime('%d.%m.%Y')} ({days[d.weekday()]})"


def parse_date_label(label: str) -> str:
    return label.split(" ")[0]


def to_iso_date(date_str: str) -> str:
    return datetime.strptime(date_str, "%d.%m.%Y").strftime("%Y-%m-%d")


def time_to_minutes(v: str) -> int:
    h, m = map(int, v.split(":"))
    return h * 60 + m


def minutes_to_time(v: int) -> str:
    return f"{v // 60:02d}:{v % 60:02d}"


def has_overlap(s1, d1, s2, d2) -> bool:
    return max(s1, s2) < min(s1 + d1, s2 + d2)


def generate_available_dates(barber_name: str) -> list:
    barber = get_barber(barber_name)
    if not barber:
        return []
    try:
        workdays = list(map(int, barber["workdays"].split(",")))
    except Exception:
        workdays = list(range(7))
    today = datetime.now()
    result = []
    for i in range(BOOKING_DAYS_AHEAD):
        day = today + timedelta(days=i)
        if day.weekday() in workdays:
            result.append(format_date_label(day))
    return result


def generate_free_times(barber_name: str, booking_date: str, duration: int) -> list:
    barber = get_barber(barber_name)
    if not barber:
        return []
    start_time = barber["start_time"] or "10:00"
    end_time   = barber["end_time"]   or "20:00"
    work_start = time_to_minutes(start_time)
    work_end   = time_to_minutes(end_time)

    now = datetime.now()
    if booking_date == now.strftime("%Y-%m-%d"):
        work_start = max(work_start, now.hour * 60 + now.minute)

    existing = get_bookings_for_barber_date(barber_name, booking_date)
    busy_slots = [(time_to_minutes(r["booking_time"]), r["duration_min"]) for r in existing]

    free, cur = [], work_start
    while cur + duration <= work_end:
        if not any(has_overlap(cur, duration, s, d) for s, d in busy_slots):
            free.append(minutes_to_time(cur))
        cur += TIME_SLOT_STEP_MINUTES
    return free


def calc_bonuses_earned(price: int, bonuses_used: int) -> int:
    """Сколько бонусов начислить за запись."""
    cashback_on = get_setting("loyalty_cashback") == "1"
    visits_on   = get_setting("loyalty_visits")   == "1"
    earned = 0
    if cashback_on:
        earned += int((price - bonuses_used) * CASHBACK_PERCENT / 100)
    if visits_on:
        earned += VISITS_BONUS_AMOUNT
    return earned


def calc_max_spend(price: int, balance: int) -> int:
    """Сколько бонусов максимум можно потратить."""
    max_by_pct = int(price * MAX_BONUS_SPEND_PCT / 100)
    return min(balance, max_by_pct)


# ── /start ─────────────────────────────────────────────────

@router.message(Command("start"))
async def cmd_start(message: Message, state: FSMContext):
    await state.clear()
    await message.answer(
        f"Добро пожаловать в {BARBERSHOP_NAME} 💎",
        reply_markup=main_keyboard(is_admin(message.from_user.id)),
    )


# ── Специалисты ────────────────────────────────────────────

@router.message(F.text == "👨‍🔧 Специалисты")
async def show_specialists(message: Message):
    barbers = get_barbers()
    if not barbers:
        await message.answer("Список барберов пуст")
        return
    await message.answer("Наши специалисты:", reply_markup=specialists_keyboard([b["name"] for b in barbers]))


@router.callback_query(F.data.startswith("show_barber:"))
async def show_barber_card(callback: CallbackQuery):
    barber = get_barber(callback.data.split(":")[1])
    if not barber:
        await callback.answer("Барбер не найден", show_alert=True)
        return
    text = (
        f"💈 <b>{barber['name']}</b>\n\n"
        f"📅 Стаж: {barber['experience']}\n"
        f"✂️ Специализация: {barber['specialization']}\n"
        f"🔥 Сильные стороны: {barber['strong_sides']}\n\n"
        f"{barber['description']}"
    )
    await callback.message.answer_photo(photo=barber["photo"], caption=text, parse_mode="HTML")
    await callback.answer()


# ── Услуги / Адрес ─────────────────────────────────────────

@router.message(F.text == "💈 Услуги и цены")
async def show_services_info(message: Message):
    text = "💈 <b>Услуги и цены:</b>\n\n"
    for name, info in SERVICES.items():
        text += f"• {name} — {info['price']} ₽ ({info['duration']} мин)\n"
    await message.answer(text, parse_mode="HTML",
                         reply_markup=main_keyboard(is_admin(message.from_user.id)))


@router.message(F.text == "📍 Адрес")
async def show_address(message: Message):
    await message.answer(
        f"📍 Адрес: {ADDRESS}\n📞 Контакты: {CONTACTS}",
        reply_markup=main_keyboard(is_admin(message.from_user.id)),
    )


# ── Мои бонусы ─────────────────────────────────────────────

@router.message(F.text == "🎁 Мои бонусы")
async def show_my_bonuses(message: Message):
    uid = message.from_user.id
    balance = get_bonus_balance(uid)
    log = get_bonus_log(uid, 5)
    cashback_on = get_setting("loyalty_cashback") == "1"
    visits_on   = get_setting("loyalty_visits")   == "1"

    text = f"🎁 <b>Ваши бонусы: {balance} ₽</b>\n\n"
    if cashback_on:
        text += f"• Кэшбэк {CASHBACK_PERCENT}% от каждой записи\n"
    if visits_on:
        text += f"• +{VISITS_BONUS_AMOUNT} бонусов за каждый визит\n"
    text += f"• Тратить можно до {MAX_BONUS_SPEND_PCT}% от суммы записи\n\n"

    if log:
        text += "📋 <b>Последние операции:</b>\n"
        for entry in log:
            sign = "+" if entry["delta"] > 0 else ""
            text += f"  {sign}{entry['delta']} — {entry['reason']} ({entry['created_at'][:10]})\n"

    await message.answer(text, parse_mode="HTML",
                         reply_markup=main_keyboard(is_admin(uid)))


# ── Отмена записи (клиент) ─────────────────────────────────

@router.message(F.text == "❌ Отменить запись")
async def show_my_bookings(message: Message):
    bookings = get_active_bookings_for_user(message.from_user.id)
    if not bookings:
        await message.answer("У вас нет активных записей.",
                             reply_markup=main_keyboard(is_admin(message.from_user.id)))
        return
    await message.answer("Ваши активные записи. Нажмите для отмены:",
                         reply_markup=cancel_bookings_keyboard(bookings))


@router.callback_query(F.data.startswith("cancel_booking:"))
async def handle_cancel_booking(callback: CallbackQuery):
    action = callback.data.split(":")[1]
    if action == "close":
        await callback.message.delete()
        await callback.answer()
        return
    if action == "back":
        bookings = get_active_bookings_for_user(callback.from_user.id)
        if bookings:
            await callback.message.edit_reply_markup(reply_markup=cancel_bookings_keyboard(bookings))
        else:
            await callback.message.edit_text("У вас нет активных записей.")
        await callback.answer()
        return
    try:
        booking_id = int(action)
    except ValueError:
        await callback.answer("Ошибка", show_alert=True)
        return
    booking = get_booking_by_id(booking_id)
    if not booking or booking["user_id"] != callback.from_user.id:
        await callback.answer("Запись не найдена", show_alert=True)
        return
    if booking["status"] != "active":
        await callback.answer("Запись уже отменена", show_alert=True)
        return
    text = (
        f"Отменить запись?\n\n"
        f"💈 {booking['barber']} | ✂️ {booking['service']}\n"
        f"📅 {booking['booking_date']} в {booking['booking_time']}"
    )
    await callback.message.edit_text(text, reply_markup=confirm_cancel_keyboard(booking_id))
    await callback.answer()


@router.callback_query(F.data.startswith("confirm_cancel:"))
async def handle_confirm_cancel(callback: CallbackQuery):
    try:
        booking_id = int(callback.data.split(":")[1])
    except ValueError:
        await callback.answer("Ошибка", show_alert=True)
        return
    booking = get_booking_by_id(booking_id)
    if not booking or booking["user_id"] != callback.from_user.id:
        await callback.answer("Ошибка", show_alert=True)
        return
    if booking["status"] != "active":
        await callback.message.edit_text("Запись уже была отменена.")
        await callback.answer()
        return

    cancel_booking(booking_id)

    # Возвращаем потраченные бонусы
    if booking["bonuses_used"] > 0:
        add_bonuses(booking["user_id"], booking["bonuses_used"],
                    booking_id, "Возврат при отмене записи")

    for admin_id in ADMIN_IDS:
        try:
            await callback.bot.send_message(
                admin_id,
                f"❌ Клиент отменил запись!\n\n"
                f"👤 {booking['client_name']} | 📞 {booking['phone']}\n"
                f"💈 {booking['barber']} | ✂️ {booking['service']}\n"
                f"📅 {booking['booking_date']} в {booking['booking_time']}",
            )
        except Exception:
            pass

    await callback.message.edit_text(
        f"✅ Запись отменена.\n💈 {booking['barber']} | ✂️ {booking['service']}\n"
        f"📅 {booking['booking_date']} в {booking['booking_time']}\n\nБудем рады видеть вас снова!"
    )
    await callback.answer("Запись отменена", show_alert=True)


# ── Отмена записи (админ) ──────────────────────────────────

@router.message(F.text == "🗑 Отменить запись (админ)")
async def admin_show_all_bookings(message: Message):
    if not is_admin(message.from_user.id):
        return
    bookings = get_all_active_bookings()
    if not bookings:
        await message.answer("Активных записей нет.", reply_markup=admin_keyboard())
        return
    await message.answer(f"Активные записи ({len(bookings)} шт.):",
                         reply_markup=admin_cancel_bookings_keyboard(bookings))


@router.callback_query(F.data.startswith("admin_cancel:"))
async def handle_admin_cancel(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        await callback.answer("Доступ запрещён", show_alert=True)
        return
    action = callback.data.split(":")[1]
    if action == "close":
        await callback.message.delete()
        await callback.answer()
        return
    if action == "back":
        bookings = get_all_active_bookings()
        if bookings:
            await callback.message.edit_reply_markup(
                reply_markup=admin_cancel_bookings_keyboard(bookings))
        else:
            await callback.message.edit_text("Активных записей нет.")
        await callback.answer()
        return
    try:
        booking_id = int(action)
    except ValueError:
        await callback.answer("Ошибка", show_alert=True)
        return
    booking = get_booking_by_id(booking_id)
    if not booking or booking["status"] != "active":
        await callback.answer("Запись не найдена или уже отменена", show_alert=True)
        return
    await callback.message.edit_text(
        f"Отменить запись?\n\n#{booking['id']} | 👤 {booking['client_name']}\n"
        f"📞 {booking['phone']}\n💈 {booking['barber']} | ✂️ {booking['service']}\n"
        f"📅 {booking['booking_date']} в {booking['booking_time']}",
        reply_markup=admin_confirm_cancel_keyboard(booking_id),
    )
    await callback.answer()


@router.callback_query(F.data.startswith("admin_confirm_cancel:"))
async def handle_admin_confirm_cancel(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        await callback.answer("Доступ запрещён", show_alert=True)
        return
    try:
        booking_id = int(callback.data.split(":")[1])
    except ValueError:
        await callback.answer("Ошибка", show_alert=True)
        return
    booking = get_booking_by_id(booking_id)
    if not booking or booking["status"] != "active":
        await callback.message.edit_text("Запись уже была отменена.")
        await callback.answer()
        return
    cancel_booking(booking_id)
    if booking["bonuses_used"] > 0:
        add_bonuses(booking["user_id"], booking["bonuses_used"],
                    booking_id, "Возврат при отмене администратором")
    try:
        await callback.bot.send_message(
            booking["user_id"],
            f"❌ Ваша запись отменена администратором.\n\n"
            f"💈 {booking['barber']} | ✂️ {booking['service']}\n"
            f"📅 {booking['booking_date']} в {booking['booking_time']}\n\n"
            "Для повторной записи нажмите ✂️ Записаться",
        )
    except Exception:
        pass
    await callback.message.edit_text(
        f"✅ Запись #{booking_id} отменена.\n👤 {booking['client_name']} уведомлён.")
    await callback.answer("Запись отменена", show_alert=True)


# ── Кнопка "Назад" ─────────────────────────────────────────

@router.message(F.text == "⬅️ Назад")
async def go_back(message: Message, state: FSMContext):
    cur = await state.get_state()
    if cur == BookingState.phone.state:
        await state.set_state(BookingState.name)
        await message.answer("Как вас зовут?")
    elif cur == BookingState.barber.state:
        # Если клиент уже в БД — при нажатии "назад" из выбора барбера
        # возвращаем к телефону только если нет сохранённых данных
        data = await state.get_data()
        if data.get("from_existing_client", False):
            # Новый клиент пришёл уже с данными — некуда возвращаться, идём в меню
            await state.clear()
            await message.answer("Главное меню:",
                                 reply_markup=main_keyboard(is_admin(message.from_user.id)))
        else:
            await state.set_state(BookingState.phone)
            await message.answer("Введите номер телефона:", reply_markup=phone_keyboard())
    elif cur == BookingState.service.state:
        await state.set_state(BookingState.barber)
        await message.answer("Выберите мастера:", reply_markup=barbers_keyboard(get_barber_names()))
    elif cur == BookingState.date.state:
        await state.set_state(BookingState.service)
        await message.answer("Выберите услугу:", reply_markup=services_keyboard(list(SERVICES.keys())))
    elif cur == BookingState.time.state:
        data = await state.get_data()
        dates = generate_available_dates(data.get("barber", ""))
        await state.set_state(BookingState.date)
        await message.answer("Выберите дату:", reply_markup=dates_keyboard(dates))
    elif cur == BookingState.use_bonuses.state:
        data = await state.get_data()
        await state.set_state(BookingState.time)
        free_times = generate_free_times(data["barber"], data["booking_date_iso"],
                                         SERVICES[data["service"]]["duration"])
        await message.answer("Выберите время:", reply_markup=times_keyboard(free_times))
    elif cur and cur.startswith("BarberAdminState"):
        await state.clear()
        await message.answer("🛠 Админ-панель:", reply_markup=admin_keyboard())
    elif cur == AdminState.broadcast_text.state:
        await state.clear()
        await message.answer("🛠 Админ-панель:", reply_markup=admin_keyboard())
    else:
        await state.clear()
        await message.answer("Главное меню:",
                             reply_markup=main_keyboard(is_admin(message.from_user.id)))


# ── Запись — FSM ───────────────────────────────────────────

@router.message(F.text == "✂️ Записаться")
async def start_booking(message: Message, state: FSMContext):
    await state.clear()
    uid = message.from_user.id

    # Проверяем клиента в БД — если уже записывался, пропускаем имя и телефон
    existing = get_client(uid)

    if existing and existing["client_name"] and existing["phone"] \
            and str(existing["client_name"]).strip() and str(existing["phone"]).strip():
        await state.update_data(
            client_name=existing["client_name"],
            phone=existing["phone"],
            from_existing_client=True,
        )
        barbers = get_barber_names()
        if not barbers:
            await message.answer("К сожалению, барберы пока недоступны. Попробуйте позже.",
                                 reply_markup=main_keyboard(is_admin(uid)))
            return
        await message.answer(
            f"С возвращением, {existing['client_name']}! 👋\nВыберите мастера:",
            reply_markup=barbers_keyboard(barbers),
        )
        await state.set_state(BookingState.barber)
    else:
        # Новый клиент
        await state.update_data(from_existing_client=False)
        await message.answer("Как вас зовут?")
        await state.set_state(BookingState.name)


@router.message(BookingState.name)
async def get_name(message: Message, state: FSMContext):
    if message.text == "⬅️ Назад":
        await go_back(message, state)
        return
    await state.update_data(client_name=message.text)
    await message.answer("Введите номер телефона:", reply_markup=phone_keyboard())
    await state.set_state(BookingState.phone)


@router.message(BookingState.phone, F.contact)
async def get_phone_contact(message: Message, state: FSMContext):
    data = await state.get_data()
    phone = message.contact.phone_number
    await state.update_data(phone=phone)

    # Сохраняем клиента сразу — чтобы при следующей записи не спрашивать данные
    upsert_client(
        message.from_user.id,
        data["client_name"],
        phone,
        message.from_user.username,
        message.from_user.full_name,
    )

    barbers = get_barber_names()
    await message.answer("Выберите мастера:", reply_markup=barbers_keyboard(barbers))
    await state.set_state(BookingState.barber)


@router.message(BookingState.phone, F.text)
async def get_phone_text(message: Message, state: FSMContext):
    if message.text == "⬅️ Назад":
        await go_back(message, state)
        return
    phone = message.text.strip()
    if not re.match(r'^(\+7|7|8)\d{10}$', phone):
        await message.answer("Введите номер в формате: +79991234567")
        return
    data = await state.get_data()
    await state.update_data(phone=phone)

    # Сохраняем клиента сразу — чтобы при следующей записи не спрашивать данные
    upsert_client(
        message.from_user.id,
        data["client_name"],
        phone,
        message.from_user.username,
        message.from_user.full_name,
    )

    barbers = get_barber_names()
    await message.answer("Выберите мастера:", reply_markup=barbers_keyboard(barbers))
    await state.set_state(BookingState.barber)


@router.message(BookingState.barber)
async def select_barber(message: Message, state: FSMContext):
    if message.text == "⬅️ Назад":
        await go_back(message, state)
        return
    names = get_barber_names()
    if message.text not in names:
        await message.answer("Выберите мастера кнопкой", reply_markup=barbers_keyboard(names))
        return
    await state.update_data(barber=message.text)
    await message.answer("Выберите услугу:", reply_markup=services_keyboard(list(SERVICES.keys())))
    await state.set_state(BookingState.service)


@router.message(BookingState.service)
async def get_service(message: Message, state: FSMContext):
    if message.text == "⬅️ Назад":
        await go_back(message, state)
        return
    if message.text not in SERVICES:
        await message.answer("Выберите услугу кнопкой", reply_markup=services_keyboard(list(SERVICES.keys())))
        return
    await state.update_data(service=message.text)
    data = await state.get_data()
    dates = generate_available_dates(data["barber"])
    await message.answer("Выберите дату:", reply_markup=dates_keyboard(dates))
    await state.set_state(BookingState.date)


@router.message(BookingState.date)
async def get_date(message: Message, state: FSMContext):
    if message.text == "⬅️ Назад":
        await go_back(message, state)
        return
    data = await state.get_data()
    valid_dates = generate_available_dates(data["barber"])
    if message.text not in valid_dates:
        await message.answer("Выберите дату кнопкой", reply_markup=dates_keyboard(valid_dates))
        return
    booking_date = parse_date_label(message.text)
    duration = SERVICES[data["service"]]["duration"]
    free_times = generate_free_times(data["barber"], to_iso_date(booking_date), duration)
    if not free_times:
        await message.answer("На этот день нет свободного времени, выберите другой.",
                             reply_markup=dates_keyboard(valid_dates))
        return
    await state.update_data(date=booking_date, booking_date_iso=to_iso_date(booking_date))
    await message.answer("Выберите время:", reply_markup=times_keyboard(free_times))
    await state.set_state(BookingState.time)


@router.message(BookingState.time)
async def get_time(message: Message, state: FSMContext):
    if message.text == "⬅️ Назад":
        await go_back(message, state)
        return
    data = await state.get_data()
    duration = SERVICES[data["service"]]["duration"]
    free_times = generate_free_times(data["barber"], data["booking_date_iso"], duration)
    if message.text not in free_times:
        await message.answer("Выберите время кнопкой", reply_markup=times_keyboard(free_times))
        return
    await state.update_data(booking_time=message.text)

    # Предложить потратить бонусы если есть
    uid = message.from_user.id
    balance = get_bonus_balance(uid)
    price = SERVICES[data["service"]]["price"]
    max_spend = calc_max_spend(price, balance)

    cashback_on = get_setting("loyalty_cashback") == "1"
    visits_on   = get_setting("loyalty_visits")   == "1"
    loyalty_on  = cashback_on or visits_on

    if loyalty_on and balance > 0 and max_spend > 0:
        await message.answer(
            f"💰 У вас <b>{balance} бонусов</b>.\n"
            f"Можно списать до <b>{max_spend} бонусов</b> "
            f"(до {MAX_BONUS_SPEND_PCT}% от стоимости {price} ₽).\n\n"
            "Хотите списать бонусы?",
            parse_mode="HTML",
            reply_markup=use_bonuses_keyboard(balance, max_spend),
        )
        await state.set_state(BookingState.use_bonuses)
    else:
        await _finish_booking(message, state, bonuses_used=0)


@router.message(BookingState.use_bonuses)
async def handle_use_bonuses(message: Message, state: FSMContext):
    data = await state.get_data()
    price = SERVICES[data["service"]]["price"]
    balance = get_bonus_balance(message.from_user.id)
    max_spend = calc_max_spend(price, balance)

    if message.text.startswith("✅ Да"):
        await _finish_booking(message, state, bonuses_used=max_spend)
    elif message.text.startswith("❌ Нет"):
        await _finish_booking(message, state, bonuses_used=0)
    else:
        await message.answer("Нажмите одну из кнопок.",
                             reply_markup=use_bonuses_keyboard(balance, max_spend))


async def _finish_booking(message: Message, state: FSMContext, bonuses_used: int):
    data = await state.get_data()
    uid         = message.from_user.id
    client_name = data["client_name"]
    phone       = data["phone"]
    barber      = data["barber"]
    service     = data["service"]
    booking_date    = data["date"]
    booking_date_iso= data["booking_date_iso"]
    booking_time    = data["booking_time"]
    service_price   = SERVICES[service]["price"]
    duration        = SERVICES[service]["duration"]
    appointment_at  = f"{booking_date_iso}T{booking_time}:00"

    bonuses_earned = calc_bonuses_earned(service_price, bonuses_used)
    final_price    = service_price - bonuses_used

    upsert_client(uid, client_name, phone, message.from_user.username, message.from_user.full_name)

    booking_id = create_booking(
        user_id=uid, client_name=client_name, phone=phone,
        barber=barber, service=service, service_price=service_price,
        duration_min=duration, booking_date=booking_date_iso,
        booking_time=booking_time, appointment_at=appointment_at,
        bonuses_used=bonuses_used, bonuses_earned=bonuses_earned,
    )

    if bonuses_used > 0:
        spend_bonuses(uid, bonuses_used, booking_id)
    if bonuses_earned > 0:
        add_bonuses(uid, bonuses_earned, booking_id,
                    f"Кэшбэк за запись #{booking_id}")

    schedule_booking_reminder(
        booking_id=booking_id, user_id=uid, barber=barber,
        service=service, booking_date=booking_date_iso,
        booking_time=booking_time, appointment_at=appointment_at,
    )

    bonus_info = ""
    if bonuses_used > 0:
        bonus_info += f"🎁 Списано бонусов: {bonuses_used} ₽\n"
        bonus_info += f"💳 К оплате: {final_price} ₽\n"
    if bonuses_earned > 0:
        bonus_info += f"⭐ Начислено бонусов: +{bonuses_earned}\n"

    await message.answer(
        "✅ <b>Вы успешно записаны!</b>\n\n"
        f"👤 Имя: {client_name}\n"
        f"📞 Телефон: {phone}\n"
        f"💈 Мастер: {barber}\n"
        f"✂️ Услуга: {service}\n"
        f"💵 Цена: {service_price} ₽\n"
        f"{bonus_info}"
        f"📅 Дата: {booking_date}\n"
        f"🕒 Время: {booking_time}\n\n"
        "Мы ждём вас! 💈",
        parse_mode="HTML",
        reply_markup=main_keyboard(is_admin(uid)),
    )

    # Уведомление админу
    for admin_id in ADMIN_IDS:
        try:
            await message.bot.send_message(
                admin_id,
                f"🆕 Новая запись!\n\n"
                f"👤 {client_name} | 📞 {phone}\n"
                f"💈 {barber} | ✂️ {service}\n"
                f"📅 {booking_date} в {booking_time}\n"
                f"💵 {service_price} ₽"
                + (f" (бонусы: -{bonuses_used})" if bonuses_used else ""),
            )
        except Exception:
            pass

    await state.clear()


# ── Главное меню ───────────────────────────────────────────

@router.message(F.text == "🏠 В меню")
async def go_to_menu(message: Message, state: FSMContext):
    await state.clear()
    await message.answer(
        f"Добро пожаловать в {BARBERSHOP_NAME} 💎",
        reply_markup=main_keyboard(is_admin(message.from_user.id)),
    )


# ── Админ-панель ───────────────────────────────────────────

@router.message(F.text == "🛠 Админ-панель")
@router.message(Command("admin"))
async def open_admin_panel(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        await message.answer("⛔ Доступ запрещён")
        return
    await state.clear()
    await message.answer("🛠 <b>Админ-панель</b>\n\nВыберите действие:",
                         parse_mode="HTML", reply_markup=admin_keyboard())


@router.message(F.text == "📅 Записи на сегодня")
async def admin_today(message: Message):
    if not is_admin(message.from_user.id):
        return
    today = datetime.now().strftime("%Y-%m-%d")
    bookings = get_today_bookings(today)
    if not bookings:
        await message.answer("📅 На сегодня записей нет.", reply_markup=admin_keyboard())
        return
    text = f"📅 <b>Записи на сегодня ({datetime.now().strftime('%d.%m.%Y')}):</b>\n\n"
    for b in bookings:
        text += (
            f"🕒 {b['booking_time']} — {b['client_name']}\n"
            f"   💈 {b['barber']} | ✂️ {b['service']}\n"
            f"   📞 {b['phone']} | #{b['id']}\n\n"
        )
    await message.answer(text, parse_mode="HTML", reply_markup=admin_keyboard())


@router.message(F.text == "📚 Последние записи")
async def admin_recent(message: Message):
    if not is_admin(message.from_user.id):
        return
    bookings = get_recent_bookings(15)
    if not bookings:
        await message.answer("Записей пока нет.", reply_markup=admin_keyboard())
        return
    text = "📚 <b>Последние 15 записей:</b>\n\n"
    for b in bookings:
        icon = "✅" if b["status"] == "active" else ("🏁" if b["status"] == "completed" else "❌")
        text += (
            f"{icon} #{b['id']} {b['booking_date']} {b['booking_time']}\n"
            f"   👤 {b['client_name']} | 📞 {b['phone']}\n"
            f"   💈 {b['barber']} | ✂️ {b['service']}\n\n"
        )
    await message.answer(text, parse_mode="HTML", reply_markup=admin_keyboard())


@router.message(F.text == "📖 История записей")
async def admin_history(message: Message):
    if not is_admin(message.from_user.id):
        return
    bookings = get_booking_history(50)
    if not bookings:
        await message.answer("📖 История пока пуста.", reply_markup=admin_keyboard())
        return
    completed = sum(1 for b in bookings if b["status"] == "completed")
    cancelled = sum(1 for b in bookings if b["status"] == "cancelled")
    text = (
        f"📖 <b>История записей (последние 50)</b>\n\n"
        f"🏁 Завершённых: {completed}  ❌ Отменённых: {cancelled}\n"
        + "─" * 28 + "\n\n"
    )
    for b in bookings:
        icon  = "🏁" if b["status"] == "completed" else "❌"
        label = "завершена" if b["status"] == "completed" else "отменена"
        text += (
            f"{icon} #{b['id']} {b['booking_date']} {b['booking_time']} ({label})\n"
            f"   👤 {b['client_name']} | 📞 {b['phone']}\n"
            f"   💈 {b['barber']} | ✂️ {b['service']} | 💵 {b['service_price']} ₽\n\n"
        )
    if len(text) > 4000:
        text = text[:4000] + "\n\n... (показаны последние 50)"
    await message.answer(text, parse_mode="HTML", reply_markup=admin_keyboard())


# ── Статистика ─────────────────────────────────────────────

@router.message(F.text == "📊 Статистика")
async def admin_stats_menu(message: Message):
    if not is_admin(message.from_user.id):
        return
    await message.answer("📊 Выберите период:", reply_markup=stats_period_keyboard())


@router.callback_query(F.data.startswith("stats:"))
async def admin_stats(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        await callback.answer("Доступ запрещён", show_alert=True)
        return
    period = callback.data.split(":")[1]
    today  = datetime.now()

    if period == "today":
        date_from = date_to = today.strftime("%Y-%m-%d")
        label = "Сегодня"
    elif period == "week":
        date_from = (today - timedelta(days=today.weekday())).strftime("%Y-%m-%d")
        date_to   = today.strftime("%Y-%m-%d")
        label = "Эта неделя"
    elif period == "month":
        date_from = today.replace(day=1).strftime("%Y-%m-%d")
        date_to   = today.strftime("%Y-%m-%d")
        label = "Этот месяц"
    else:
        date_from = "2000-01-01"
        date_to   = today.strftime("%Y-%m-%d")
        label = "Все время"

    s = get_stats(date_from, date_to)

    text = (
        f"📊 <b>Статистика — {label}</b>\n\n"
        f"💵 Выручка: <b>{s['revenue']} ₽</b>\n"
        f"📋 Записей: <b>{s['count']}</b>\n"
        f"👤 Новых клиентов: <b>{s['new_clients']}</b>\n\n"
    )
    if s["top_clients"]:
        text += "🏆 <b>Топ клиентов:</b>\n"
        for i, c in enumerate(s["top_clients"], 1):
            text += f"  {i}. {c['client_name']} — {c['cnt']} визитов / {c['spent']} ₽\n"
        text += "\n"
    if s["top_barbers"]:
        text += "💈 <b>Топ барберов:</b>\n"
        for i, b in enumerate(s["top_barbers"], 1):
            text += f"  {i}. {b['barber']} — {b['cnt']} записей / {b['earned']} ₽\n"
        text += "\n"
    if s["top_services"]:
        text += "✂️ <b>Топ услуг:</b>\n"
        for i, sv in enumerate(s["top_services"], 1):
            text += f"  {i}. {sv['service']} — {sv['cnt']} раз / {sv['total']} ₽\n"

    await callback.message.edit_text(text, parse_mode="HTML")
    await callback.answer()


# ── Программа лояльности (админ) ──────────────────────────

@router.message(F.text == "🎁 Программа лояльности")
async def admin_loyalty_menu(message: Message):
    if not is_admin(message.from_user.id):
        return
    cashback_on = get_setting("loyalty_cashback") == "1"
    visits_on   = get_setting("loyalty_visits")   == "1"
    text = (
        "🎁 <b>Программа лояльности</b>\n\n"
        f"Кэшбэк {CASHBACK_PERCENT}% от суммы записи\n"
        f"Фиксированные +{VISITS_BONUS_AMOUNT} баллов за визит\n\n"
        "Нажмите на режим чтобы включить/выключить:"
    )
    await message.answer(text, parse_mode="HTML",
                         reply_markup=loyalty_admin_keyboard(cashback_on, visits_on))


@router.callback_query(F.data.startswith("loyalty_toggle:"))
async def toggle_loyalty(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        await callback.answer("Доступ запрещён", show_alert=True)
        return
    action = callback.data.split(":")[1]
    if action == "close":
        await callback.message.delete()
        await callback.answer()
        return
    if action == "cashback":
        current = get_setting("loyalty_cashback") == "1"
        set_setting("loyalty_cashback", "0" if current else "1")
        await callback.answer("✅ Кэшбэк " + ("выключен" if current else "включён"))
    elif action == "visits":
        current = get_setting("loyalty_visits") == "1"
        set_setting("loyalty_visits", "0" if current else "1")
        await callback.answer("✅ Баллы за визит " + ("выключены" if current else "включены"))

    cashback_on = get_setting("loyalty_cashback") == "1"
    visits_on   = get_setting("loyalty_visits")   == "1"
    await callback.message.edit_reply_markup(
        reply_markup=loyalty_admin_keyboard(cashback_on, visits_on))


# ── Рассылка ───────────────────────────────────────────────

@router.message(F.text == "📢 Рассылка клиентам")
async def admin_broadcast_menu(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        return
    await state.clear()
    clients_count = len(get_all_clients())
    await message.answer(
        f"📢 <b>Рассылка клиентам</b>\n\nКлиентов в базе: <b>{clients_count}</b>\n\n"
        "Выберите действие:",
        parse_mode="HTML",
        reply_markup=broadcast_keyboard(),
    )


@router.callback_query(F.data.startswith("broadcast:"))
async def broadcast_action(callback: CallbackQuery, state: FSMContext):
    if not is_admin(callback.from_user.id):
        await callback.answer("Доступ запрещён", show_alert=True)
        return
    action = callback.data.split(":")[1]

    if action == "close":
        await callback.message.delete()
        await callback.answer()
        return

    if action == "now":
        await callback.message.edit_text(
            "✍️ Введите текст рассылки:\n\n(⬅️ Назад для отмены)")
        await state.set_state(AdminState.broadcast_text)
        await state.update_data(broadcast_type="now")
        await callback.answer()
        return

    if action == "schedule":
        await callback.message.edit_text(
            "✍️ Введите текст рассылки:\n\n(⬅️ Назад для отмены)")
        await state.set_state(AdminState.broadcast_text)
        await state.update_data(broadcast_type="schedule")
        await callback.answer()
        return

    if action == "history":
        history = get_broadcast_history(10)
        if not history:
            await callback.answer("История рассылок пуста", show_alert=True)
            return
        text = "📋 <b>История рассылок:</b>\n\n"
        for bc in history:
            status_icon = "✅" if bc["status"] == "sent" else "🕐"
            text += (
                f"{status_icon} {bc['created_at'][:16]}\n"
                f"   Отправлено: {bc['sent_count']} | Ошибок: {bc['fail_count']}\n"
                f"   {bc['text'][:60]}{'...' if len(bc['text']) > 60 else ''}\n\n"
            )
        await callback.message.edit_text(text, parse_mode="HTML")
        await callback.answer()
        return


@router.message(AdminState.broadcast_text)
async def broadcast_get_text(message: Message, state: FSMContext):
    if message.text == "⬅️ Назад":
        await state.clear()
        await message.answer("🛠 Админ-панель:", reply_markup=admin_keyboard())
        return
    data = await state.get_data()
    await state.update_data(broadcast_text=message.text)

    if data.get("broadcast_type") == "schedule":
        await message.answer(
            "🕐 Введите дату и время отправки в формате:\n"
            "<code>ДД.ММ.ГГГГ ЧЧ:ММ</code>\n\nНапример: 25.12.2025 10:00",
            parse_mode="HTML",
        )
        await state.set_state(AdminState.broadcast_schedule)
    else:
        clients_count = len(get_all_clients())
        await message.answer(
            f"📤 Отправить рассылку <b>{clients_count}</b> клиентам?\n\n"
            f"Текст:\n{message.text}",
            parse_mode="HTML",
            reply_markup=broadcast_confirm_keyboard(),
        )
        await state.set_state(AdminState.broadcast_confirm)


@router.message(AdminState.broadcast_schedule)
async def broadcast_get_schedule(message: Message, state: FSMContext):
    try:
        scheduled_dt = datetime.strptime(message.text.strip(), "%d.%m.%Y %H:%M")
    except ValueError:
        await message.answer("Неверный формат. Введите как: 25.12.2025 10:00")
        return
    data = await state.get_data()
    scheduled_iso = scheduled_dt.isoformat(timespec="seconds")
    create_broadcast(data["broadcast_text"], scheduled_at=scheduled_iso)
    await state.clear()
    await message.answer(
        f"✅ Рассылка запланирована на <b>{message.text}</b>",
        parse_mode="HTML",
        reply_markup=admin_keyboard(),
    )


@router.callback_query(F.data.startswith("broadcast_confirm:"))
async def broadcast_confirm(callback: CallbackQuery, state: FSMContext):
    if not is_admin(callback.from_user.id):
        await callback.answer("Доступ запрещён", show_alert=True)
        return
    action = callback.data.split(":")[1]
    if action == "no":
        await state.clear()
        await callback.message.edit_text("❌ Рассылка отменена.")
        await callback.answer()
        return

    data = await state.get_data()
    text = data.get("broadcast_text", "")
    clients = get_all_clients()
    sent, failed = 0, 0
    await callback.message.edit_text(f"📤 Отправляю {len(clients)} клиентам...")
    for c in clients:
        try:
            await callback.bot.send_message(c["user_id"], text)
            sent += 1
        except Exception:
            failed += 1
    bc_id = create_broadcast(text)
    mark_broadcast_sent(bc_id, sent, failed)
    await state.clear()
    await callback.message.edit_text(
        f"✅ Рассылка завершена.\nОтправлено: {sent} | Ошибок: {failed}")
    await callback.answer()


# ── Google Sheets ──────────────────────────────────────────

@router.message(F.text == "📤 Выгрузить в Google Sheets")
async def export_to_sheets(message: Message):
    if not is_admin(message.from_user.id):
        return
    await message.answer("⏳ Выгружаю данные в Google Sheets, подождите...")
    try:
        import asyncio
        from sheets import export_all
        bookings = get_recent_bookings(10000)
        clients  = get_all_clients()
        stats    = get_stats("2000-01-01", datetime.now().strftime("%Y-%m-%d"))
        url = await asyncio.to_thread(export_all, bookings, clients, stats)
        await message.answer(
            f"✅ Выгрузка завершена!\n\n📊 Таблица: {url}",
            reply_markup=admin_keyboard(),
        )
    except Exception as e:
        await message.answer(
            f"❌ Ошибка выгрузки:\n<code>{e}</code>\n\n"
            "Проверь credentials.json и GOOGLE_SPREADSHEET_ID в config.py",
            parse_mode="HTML",
            reply_markup=admin_keyboard(),
        )


# ── Управление барберами ───────────────────────────────────

@router.message(F.text == "👨‍🔧 Управление барберами")
async def admin_barbers_menu(message: Message):
    if not is_admin(message.from_user.id):
        return
    barbers = get_barbers()
    text = "👨‍🔧 <b>Барберы:</b>\n\n"
    text += "\n".join(f"{b['id']}. {b['name']}" for b in barbers) if barbers else "Список пуст.\n"
    text += "\n\n/add_barber — добавить\n/delete_barber ID — удалить"
    await message.answer(text, parse_mode="HTML", reply_markup=admin_keyboard())


@router.message(Command("delete_barber"))
async def delete_barber_cmd(message: Message):
    if not is_admin(message.from_user.id):
        return
    parts = message.text.split()
    if len(parts) < 2:
        await message.answer("Используй: /delete_barber ID")
        return
    try:
        delete_barber(int(parts[1]))
        await message.answer("✅ Барбер удалён", reply_markup=admin_keyboard())
    except ValueError:
        await message.answer("ID должен быть числом")


@router.message(Command("add_barber"))
async def add_barber_start(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        return
    await message.answer("Добавление барбера.\n\nВведите имя:")
    await state.set_state(BarberAdminState.name)


@router.message(BarberAdminState.name)
async def barber_name(message: Message, state: FSMContext):
    if message.text == "⬅️ Назад":
        await state.clear()
        await message.answer("🛠 Админ-панель:", reply_markup=admin_keyboard())
        return
    await state.update_data(name=message.text)
    await message.answer("Введите стаж (например: 5 лет):")
    await state.set_state(BarberAdminState.experience)


@router.message(BarberAdminState.experience)
async def barber_experience(message: Message, state: FSMContext):
    if message.text == "⬅️ Назад":
        await state.set_state(BarberAdminState.name)
        await message.answer("Введите имя:")
        return
    await state.update_data(experience=message.text)
    await message.answer("Введите специализацию:")
    await state.set_state(BarberAdminState.specialization)


@router.message(BarberAdminState.specialization)
async def barber_specialization(message: Message, state: FSMContext):
    if message.text == "⬅️ Назад":
        await state.set_state(BarberAdminState.experience)
        await message.answer("Введите стаж:")
        return
    await state.update_data(specialization=message.text)
    await message.answer("Введите сильные стороны:")
    await state.set_state(BarberAdminState.strong_sides)


@router.message(BarberAdminState.strong_sides)
async def barber_strong_sides(message: Message, state: FSMContext):
    if message.text == "⬅️ Назад":
        await state.set_state(BarberAdminState.specialization)
        await message.answer("Введите специализацию:")
        return
    await state.update_data(strong_sides=message.text)
    await message.answer("Введите описание:")
    await state.set_state(BarberAdminState.description)


@router.message(BarberAdminState.description)
async def barber_description(message: Message, state: FSMContext):
    if message.text == "⬅️ Назад":
        await state.set_state(BarberAdminState.strong_sides)
        await message.answer("Введите сильные стороны:")
        return
    await state.update_data(description=message.text)
    await message.answer("Отправьте фото или введите file_id:")
    await state.set_state(BarberAdminState.photo)


@router.message(BarberAdminState.photo)
async def barber_photo(message: Message, state: FSMContext):
    if message.text == "⬅️ Назад":
        await state.set_state(BarberAdminState.description)
        await message.answer("Введите описание:")
        return
    photo_id = message.photo[-1].file_id if message.photo else (message.text or "").strip()
    if not photo_id:
        await message.answer("Отправьте фото или введите file_id")
        return
    data = await state.get_data()
    add_barber(data["name"], data["experience"], data["specialization"],
               data["strong_sides"], data["description"], photo_id)
    await state.clear()
    await message.answer(f"✅ Барбер {data['name']} добавлен!", reply_markup=admin_keyboard())


# ── Debug ──────────────────────────────────────────────────

@router.message()
async def debug_message(message: Message):
    print("DEBUG:", message.text)
