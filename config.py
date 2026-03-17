BOT_TOKEN = "8665621903:AAFLNR3ro75pZpw6HgebU0GF7__bLR5dpP4"
ADMIN_IDS = [5321829773, 1433968449]  # Вставь свой Telegram ID

TIMEZONE = "Europe/Moscow"
BARBERSHOP_NAME = "Barbershop Ultimate"
ADDRESS = "г. Казань, ул. Кремлевская, 10"
CONTACTS = "+7 (999) 123-45-67"

REMINDER_HOURS_BEFORE = 2
TIME_SLOT_STEP_MINUTES = 30
BOOKING_DAYS_AHEAD = 30

# ── Google Sheets ──────────────────────────────────────────
# Создай сервисный аккаунт в Google Cloud Console,
# скачай JSON-ключ и укажи путь ниже.
GOOGLE_CREDENTIALS_FILE = "credentials.json"
GOOGLE_SPREADSHEET_ID = "1wB6GvZhKtZ_11ZLuEgcwLbHsieohoqDIWwUd0siM8_k"   # из URL таблицы

# ── Программа лояльности ───────────────────────────────────
# Оба режима можно включать/выключать через админ-панель.
# Здесь — значения по умолчанию при первом запуске.
LOYALTY_CASHBACK_ENABLED_DEFAULT = True
LOYALTY_VISITS_ENABLED_DEFAULT   = True

CASHBACK_PERCENT     = 5      # % от суммы записи → начисляется бонусами
VISITS_BONUS_AMOUNT  = 100    # бонусов за каждый визит (фиксировано)
MAX_BONUS_SPEND_PCT  = 30     # максимум % от суммы, который можно потратить бонусами

# ── Услуги ─────────────────────────────────────────────────
SERVICES = {
    "Стрижка":               {"price": 1500, "duration": 60},
    "Стрижка + борода":      {"price": 2200, "duration": 90},
    "Бритьё":                {"price": 1200, "duration": 45},
    "Моделирование бороды":  {"price": 1000, "duration": 30},
}
