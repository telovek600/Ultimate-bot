from aiogram.fsm.state import State, StatesGroup


class BookingState(StatesGroup):
    name         = State()
    phone        = State()
    barber       = State()
    service      = State()
    date         = State()
    time         = State()
    use_bonuses  = State()   # предложить списать бонусы


class AdminState(StatesGroup):
    broadcast_text      = State()
    broadcast_confirm   = State()
    broadcast_schedule  = State()   # ввод даты/времени отложенной рассылки
    stats_period        = State()   # выбор периода статистики


class BarberAdminState(StatesGroup):
    name           = State()
    experience     = State()
    specialization = State()
    strong_sides   = State()
    description    = State()
    photo          = State()


class LoyaltyAdminState(StatesGroup):
    menu = State()
