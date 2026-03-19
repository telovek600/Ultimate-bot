"""
Google Sheets интеграция.

Установка зависимостей:
    pip install gspread google-auth

Настройка:
1. Создай проект в Google Cloud Console
2. Включи Google Sheets API и Google Drive API
3. Создай сервисный аккаунт → скачай JSON-ключ → назови credentials.json
4. Открой таблицу и дай сервисному аккаунту доступ (редактор)
5. Вставь ID таблицы в config.py → GOOGLE_SPREADSHEET_ID
"""

import gspread
import os, json
from google.oauth2.service_account import Credentials
from datetime import datetime

from config import GOOGLE_CREDENTIALS_FILE, GOOGLE_SPREADSHEET_ID

SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive",
]

_gc = None


def _get_client():
    global _gc
    if _gc is None:
        creds_json = os.environ.get("GOOGLE_CREDENTIALS_JSON")
        if creds_json:
            creds = Credentials.from_service_account_info(
                json.loads(creds_json), scopes=SCOPES
            )
        else:
            creds = Credentials.from_service_account_file(
                GOOGLE_CREDENTIALS_FILE, scopes=SCOPES
            )
        _gc = gspread.authorize(creds)
    return _gc


def _get_or_create_sheet(spreadsheet, title: str, headers: list):
    try:
        ws = spreadsheet.worksheet(title)
    except gspread.WorksheetNotFound:
        ws = spreadsheet.add_worksheet(title=title, rows=1000, cols=len(headers))
        ws.append_row(headers)
    return ws


def _safe(row, key, default=""):
    """Безопасное получение из sqlite3.Row или dict."""
    try:
        val = row[key]
        return val if val is not None else default
    except (IndexError, KeyError):
        return default


def export_all(bookings: list, clients: list, stats: dict):
    gc = _get_client()
    sh = gc.open_by_key(GOOGLE_SPREADSHEET_ID)

    # ── Лист "Записи" ──────────────────────────────────────
    ws_bookings = _get_or_create_sheet(sh, "Записи", [
        "ID", "Дата", "Время", "Клиент", "Телефон",
        "Барбер", "Услуга", "Цена", "Бонусов потрачено",
        "Бонусов начислено", "Статус", "Создано",
    ])
    ws_bookings.clear()
    ws_bookings.append_row([
        "ID", "Дата", "Время", "Клиент", "Телефон",
        "Барбер", "Услуга", "Цена", "Бонусов потрачено",
        "Бонусов начислено", "Статус", "Создано",
    ])
    rows_b = []
    for b in bookings:
        rows_b.append([
            _safe(b, "id"), _safe(b, "booking_date"), _safe(b, "booking_time"),
            _safe(b, "client_name"), _safe(b, "phone"), _safe(b, "barber"),
            _safe(b, "service"), _safe(b, "service_price", 0),
            _safe(b, "bonuses_used", 0), _safe(b, "bonuses_earned", 0),
            _safe(b, "status"), _safe(b, "created_at"),
        ])
    if rows_b:
        ws_bookings.append_rows(rows_b)

    # ── Лист "Клиенты" ─────────────────────────────────────
    ws_clients = _get_or_create_sheet(sh, "Клиенты", [
        "ID", "Имя", "Телефон", "Username",
        "Бонусов", "Визитов", "Потрачено ₽",
        "Дата рождения", "Первый визит", "Последний визит",
    ])
    ws_clients.clear()
    ws_clients.append_row([
        "ID", "Имя", "Телефон", "Username",
        "Бонусов", "Визитов", "Потрачено ₽",
        "Дата рождения", "Первый визит", "Последний визит",
    ])
    rows_c = []
    for c in clients:
        rows_c.append([
            _safe(c, "user_id"), _safe(c, "client_name"), _safe(c, "phone"),
            _safe(c, "username"), _safe(c, "bonus_points", 0),
            _safe(c, "visits_count", 0), _safe(c, "total_spent", 0),
            _safe(c, "birth_date"), _safe(c, "first_seen"), _safe(c, "last_seen"),
        ])
    if rows_c:
        ws_clients.append_rows(rows_c)

    # ── Лист "Статистика" ──────────────────────────────────
    ws_stats = _get_or_create_sheet(sh, "Статистика", ["Показатель", "Значение"])
    ws_stats.clear()
    ws_stats.append_row(["Показатель", "Значение"])
    exported_at = datetime.now().strftime("%d.%m.%Y %H:%M")
    ws_stats.append_rows([
        ["Дата выгрузки",  exported_at],
        ["Всего записей",  stats.get("count", 0)],
        ["Выручка ₽",      stats.get("revenue", 0)],
        ["Новых клиентов", stats.get("new_clients", 0)],
        ["", ""],
        ["Топ клиентов", ""],
    ])
    for tc in stats.get("top_clients", []):
        ws_stats.append_row([
            _safe(tc, "client_name"),
            f"{_safe(tc, 'cnt', 0)} визитов / {_safe(tc, 'spent', 0)} ₽"
        ])
    ws_stats.append_rows([["", ""], ["Топ барберов", ""]])
    for tb in stats.get("top_barbers", []):
        ws_stats.append_row([
            _safe(tb, "barber"),
            f"{_safe(tb, 'cnt', 0)} записей / {_safe(tb, 'earned', 0)} ₽"
        ])
    ws_stats.append_rows([["", ""], ["Топ услуг", ""]])
    for ts in stats.get("top_services", []):
        ws_stats.append_row([
            _safe(ts, "service"),
            f"{_safe(ts, 'cnt', 0)} раз / {_safe(ts, 'total', 0)} ₽"
        ])

    return sh.url
