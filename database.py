import sqlite3
from datetime import datetime
from typing import Optional

DB_NAME = "ultimate.db"

# check_same_thread=False нужен для aiogram (async)
# WAL-режим снижает вероятность "database is locked" при одновременных запросах
conn = sqlite3.connect(DB_NAME, check_same_thread=False)
conn.row_factory = sqlite3.Row
conn.execute("PRAGMA journal_mode=WAL")
conn.execute("PRAGMA foreign_keys=ON")


def init_db():
    # ── Клиенты ────────────────────────────────────────────
    conn.execute("""
    CREATE TABLE IF NOT EXISTS clients (
        user_id      INTEGER PRIMARY KEY,
        client_name  TEXT,
        phone        TEXT,
        username     TEXT,
        full_name    TEXT,
        bonus_points INTEGER DEFAULT 0,
        total_spent  INTEGER DEFAULT 0,
        visits_count INTEGER DEFAULT 0,
        birth_date   TEXT,
        first_seen   TEXT,
        last_seen    TEXT
    )
    """)

    # ── Записи ─────────────────────────────────────────────
    conn.execute("""
    CREATE TABLE IF NOT EXISTS bookings (
        id             INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id        INTEGER,
        client_name    TEXT,
        phone          TEXT,
        barber         TEXT,
        service        TEXT,
        service_price  INTEGER,
        duration_min   INTEGER,
        booking_date   TEXT,
        booking_time   TEXT,
        appointment_at TEXT,
        status         TEXT DEFAULT 'active',
        reminded       INTEGER DEFAULT 0,
        bonuses_used   INTEGER DEFAULT 0,
        bonuses_earned INTEGER DEFAULT 0,
        created_at     TEXT
    )
    """)

    # ── Барберы ────────────────────────────────────────────
    conn.execute("""
    CREATE TABLE IF NOT EXISTS barbers (
        id             INTEGER PRIMARY KEY AUTOINCREMENT,
        name           TEXT UNIQUE,
        experience     TEXT,
        specialization TEXT,
        strong_sides   TEXT,
        description    TEXT,
        photo          TEXT,
        workdays       TEXT DEFAULT '0,1,2,3,4,5,6',
        start_time     TEXT DEFAULT '10:00',
        end_time       TEXT DEFAULT '20:00'
    )
    """)

    # ── Настройки (key-value) ──────────────────────────────
    conn.execute("""
    CREATE TABLE IF NOT EXISTS settings (
        key   TEXT PRIMARY KEY,
        value TEXT
    )
    """)

    # ── Рассылки ───────────────────────────────────────────
    conn.execute("""
    CREATE TABLE IF NOT EXISTS broadcasts (
        id           INTEGER PRIMARY KEY AUTOINCREMENT,
        text         TEXT,
        scheduled_at TEXT,
        sent_at      TEXT,
        status       TEXT DEFAULT 'pending',
        sent_count   INTEGER DEFAULT 0,
        fail_count   INTEGER DEFAULT 0,
        created_at   TEXT
    )
    """)

    # ── Лог транзакций бонусов ─────────────────────────────
    conn.execute("""
    CREATE TABLE IF NOT EXISTS bonus_log (
        id         INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id    INTEGER,
        booking_id INTEGER,
        delta      INTEGER,
        reason     TEXT,
        created_at TEXT
    )
    """)

    # Миграция barbers — добавляем колонки если их нет
    for col, default in [
        ("workdays",   "'0,1,2,3,4,5,6'"),
        ("start_time", "'10:00'"),
        ("end_time",   "'20:00'"),
    ]:
        try:
            conn.execute(f"ALTER TABLE barbers ADD COLUMN {col} TEXT DEFAULT {default}")
        except Exception:
            pass

    # Значения настроек по умолчанию
    from config import LOYALTY_CASHBACK_ENABLED_DEFAULT, LOYALTY_VISITS_ENABLED_DEFAULT
    _set_default("loyalty_cashback",            "1" if LOYALTY_CASHBACK_ENABLED_DEFAULT else "0")
    _set_default("loyalty_visits",              "1" if LOYALTY_VISITS_ENABLED_DEFAULT   else "0")
    _set_default("broadcast_schedule_enabled",  "0")
    _set_default("broadcast_schedule_day",      "0")   # 0=Пн … 6=Вс, "every" = каждый день
    _set_default("broadcast_schedule_time",     "10:00")
    _set_default("broadcast_schedule_text",     "")

    conn.commit()


def _set_default(key: str, value: str):
    conn.execute("INSERT OR IGNORE INTO settings (key, value) VALUES (?, ?)", (key, value))


# ── Settings ───────────────────────────────────────────────

def get_setting(key: str) -> Optional[str]:
    row = conn.execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
    return row["value"] if row else None


def set_setting(key: str, value: str):
    conn.execute("INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)", (key, value))
    conn.commit()


# ── Clients ────────────────────────────────────────────────

def upsert_client(user_id: int, client_name: str, phone: str,
                  username: Optional[str], full_name: Optional[str],
                  birth_date: Optional[str] = None):
    now = datetime.now().isoformat(timespec="seconds")
    existing = conn.execute(
        "SELECT user_id FROM clients WHERE user_id=?", (user_id,)
    ).fetchone()
    if existing:
        conn.execute("""
        UPDATE clients
        SET client_name=?, phone=?, username=?, full_name=?, last_seen=?
        WHERE user_id=?
        """, (client_name, phone, username, full_name, now, user_id))
        if birth_date:
            conn.execute(
                "UPDATE clients SET birth_date=? WHERE user_id=?", (birth_date, user_id)
            )
    else:
        conn.execute("""
        INSERT INTO clients
            (user_id, client_name, phone, username, full_name,
             birth_date, first_seen, last_seen)
        VALUES (?,?,?,?,?,?,?,?)
        """, (user_id, client_name, phone, username, full_name, birth_date, now, now))
    conn.commit()


def get_client(user_id: int):
    return conn.execute("SELECT * FROM clients WHERE user_id=?", (user_id,)).fetchone()


def get_all_clients():
    return conn.execute("SELECT * FROM clients ORDER BY last_seen DESC").fetchall()


def get_clients_not_visited_since(date_iso: str):
    """Клиенты, у которых last_seen раньше указанной даты или NULL."""
    return conn.execute("""
    SELECT * FROM clients
    WHERE last_seen < ? OR last_seen IS NULL
    """, (date_iso,)).fetchall()


# ── Bonus operations ───────────────────────────────────────

def add_bonuses(user_id: int, amount: int, booking_id: Optional[int], reason: str):
    now = datetime.now().isoformat(timespec="seconds")
    conn.execute(
        "UPDATE clients SET bonus_points = bonus_points + ? WHERE user_id=?",
        (amount, user_id)
    )
    conn.execute("""
    INSERT INTO bonus_log (user_id, booking_id, delta, reason, created_at)
    VALUES (?,?,?,?,?)
    """, (user_id, booking_id, amount, reason, now))
    conn.commit()


def spend_bonuses(user_id: int, amount: int, booking_id: Optional[int]):
    now = datetime.now().isoformat(timespec="seconds")
    conn.execute(
        "UPDATE clients SET bonus_points = MAX(0, bonus_points - ?) WHERE user_id=?",
        (amount, user_id)
    )
    conn.execute("""
    INSERT INTO bonus_log (user_id, booking_id, delta, reason, created_at)
    VALUES (?,?,?,?,?)
    """, (user_id, booking_id, -amount, "Списание при записи", now))
    conn.commit()


def get_bonus_balance(user_id: int) -> int:
    row = conn.execute(
        "SELECT bonus_points FROM clients WHERE user_id=?", (user_id,)
    ).fetchone()
    return int(row["bonus_points"]) if row else 0


def get_bonus_log(user_id: int, limit: int = 10):
    return conn.execute("""
    SELECT * FROM bonus_log WHERE user_id=? ORDER BY created_at DESC LIMIT ?
    """, (user_id, limit)).fetchall()


# ── Bookings ───────────────────────────────────────────────

def create_booking(user_id, client_name, phone, barber, service,
                   service_price, duration_min, booking_date,
                   booking_time, appointment_at,
                   bonuses_used=0, bonuses_earned=0) -> int:
    now = datetime.now().isoformat(timespec="seconds")
    cur = conn.execute("""
    INSERT INTO bookings
        (user_id, client_name, phone, barber, service, service_price,
         duration_min, booking_date, booking_time, appointment_at,
         bonuses_used, bonuses_earned, created_at)
    VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)
    """, (user_id, client_name, phone, barber, service, service_price,
          duration_min, booking_date, booking_time, appointment_at,
          bonuses_used, bonuses_earned, now))
    conn.commit()
    return cur.lastrowid


def get_bookings_for_barber_date(barber: str, booking_date: str):
    return conn.execute("""
    SELECT booking_time, duration_min FROM bookings
    WHERE barber=? AND booking_date=? AND status='active'
    ORDER BY booking_time
    """, (barber, booking_date)).fetchall()


def get_today_bookings(today_date: str):
    return conn.execute("""
    SELECT * FROM bookings
    WHERE booking_date=? AND status='active'
    ORDER BY booking_time
    """, (today_date,)).fetchall()


def get_recent_bookings(limit: int = 15):
    return conn.execute("""
    SELECT * FROM bookings ORDER BY id DESC LIMIT ?
    """, (limit,)).fetchall()


def get_active_bookings_for_user(user_id: int):
    return conn.execute("""
    SELECT * FROM bookings
    WHERE user_id=? AND status='active'
    ORDER BY booking_date ASC, booking_time ASC
    """, (user_id,)).fetchall()


def get_all_active_bookings(limit: int = 50):
    return conn.execute("""
    SELECT * FROM bookings WHERE status='active'
    ORDER BY booking_date ASC, booking_time ASC LIMIT ?
    """, (limit,)).fetchall()


def get_booking_by_id(booking_id: int):
    return conn.execute(
        "SELECT * FROM bookings WHERE id=?", (booking_id,)
    ).fetchone()


def cancel_booking(booking_id: int):
    conn.execute("UPDATE bookings SET status='cancelled' WHERE id=?", (booking_id,))
    conn.commit()


def get_future_unreminded_bookings(now_iso: str):
    return conn.execute("""
    SELECT * FROM bookings
    WHERE status='active' AND reminded=0 AND appointment_at > ?
    ORDER BY appointment_at
    """, (now_iso,)).fetchall()


def mark_booking_reminded(booking_id: int):
    conn.execute("UPDATE bookings SET reminded=1 WHERE id=?", (booking_id,))
    conn.commit()


def archive_expired_bookings() -> int:
    """Активные записи, время которых прошло → completed. Возвращает кол-во архивированных."""
    now_iso = datetime.now().strftime("%Y-%m-%d %H:%M")
    result = conn.execute("""
    UPDATE bookings SET status='completed'
    WHERE status='active' AND (booking_date || ' ' || booking_time) <= ?
    """, (now_iso,))
    conn.commit()

    # Пересчитываем visits_count и total_spent для всех клиентов
    conn.execute("""
    UPDATE clients SET
        visits_count = (
            SELECT COUNT(*) FROM bookings
            WHERE bookings.user_id = clients.user_id AND bookings.status = 'completed'
        ),
        total_spent = (
            SELECT COALESCE(SUM(service_price - bonuses_used), 0) FROM bookings
            WHERE bookings.user_id = clients.user_id AND bookings.status = 'completed'
        )
    """)
    conn.commit()
    return result.rowcount


def get_booking_history(limit: int = 50):
    return conn.execute("""
    SELECT * FROM bookings
    WHERE status IN ('completed', 'cancelled')
    ORDER BY appointment_at DESC LIMIT ?
    """, (limit,)).fetchall()


# ── Statistics ─────────────────────────────────────────────

def get_stats(date_from: str, date_to: str) -> dict:
    """Полная статистика за период (формат YYYY-MM-DD)."""
    base = "WHERE status='completed' AND booking_date BETWEEN ? AND ?"
    args = (date_from, date_to)

    revenue = conn.execute(
        f"SELECT COALESCE(SUM(service_price - bonuses_used), 0) AS r FROM bookings {base}", args
    ).fetchone()["r"]

    count = conn.execute(
        f"SELECT COUNT(*) AS c FROM bookings {base}", args
    ).fetchone()["c"]

    top_clients = conn.execute(f"""
    SELECT client_name, phone, COUNT(*) AS cnt,
           SUM(service_price - bonuses_used) AS spent
    FROM bookings {base}
    GROUP BY user_id ORDER BY cnt DESC LIMIT 5
    """, args).fetchall()

    top_barbers = conn.execute(f"""
    SELECT barber, COUNT(*) AS cnt,
           SUM(service_price - bonuses_used) AS earned
    FROM bookings {base}
    GROUP BY barber ORDER BY cnt DESC LIMIT 5
    """, args).fetchall()

    top_services = conn.execute(f"""
    SELECT service, COUNT(*) AS cnt,
           SUM(service_price) AS total
    FROM bookings {base}
    GROUP BY service ORDER BY cnt DESC LIMIT 5
    """, args).fetchall()

    new_clients = conn.execute("""
    SELECT COUNT(*) AS c FROM clients
    WHERE first_seen BETWEEN ? AND ?
    """, (date_from + "T00:00:00", date_to + "T23:59:59")).fetchone()["c"]

    return {
        "revenue":      revenue,
        "count":        count,
        "top_clients":  list(top_clients),
        "top_barbers":  list(top_barbers),
        "top_services": list(top_services),
        "new_clients":  new_clients,
    }


# ── Barbers ────────────────────────────────────────────────

def add_barber(name: str, experience: str, specialization: str, strong_sides: str,
               description: str, photo: str,
               workdays: str = "0,1,2,3,4,5,6",
               start_time: str = "10:00",
               end_time: str = "20:00"):
    conn.execute("""
    INSERT INTO barbers
        (name, experience, specialization, strong_sides,
         description, photo, workdays, start_time, end_time)
    VALUES (?,?,?,?,?,?,?,?,?)
    """, (name, experience, specialization, strong_sides,
          description, photo, workdays, start_time, end_time))
    conn.commit()


def get_barbers():
    return conn.execute("SELECT * FROM barbers ORDER BY id").fetchall()


def get_barber(name: str):
    return conn.execute("SELECT * FROM barbers WHERE name=?", (name,)).fetchone()


def delete_barber(barber_id: int):
    conn.execute("DELETE FROM barbers WHERE id=?", (barber_id,))
    conn.commit()


def get_barber_names() -> list:
    return [r["name"] for r in conn.execute("SELECT name FROM barbers ORDER BY id").fetchall()]


# ── Broadcasts ─────────────────────────────────────────────

def create_broadcast(text: str, scheduled_at: Optional[str] = None) -> int:
    now = datetime.now().isoformat(timespec="seconds")
    cur = conn.execute("""
    INSERT INTO broadcasts (text, scheduled_at, status, created_at)
    VALUES (?, ?, ?, ?)
    """, (text, scheduled_at, "pending" if scheduled_at else "manual", now))
    conn.commit()
    return cur.lastrowid


def get_pending_broadcasts(now_iso: str):
    """Запланированные рассылки, время которых пришло."""
    return conn.execute("""
    SELECT * FROM broadcasts
    WHERE status='pending' AND scheduled_at IS NOT NULL AND scheduled_at <= ?
    ORDER BY scheduled_at
    """, (now_iso,)).fetchall()


def mark_broadcast_sent(broadcast_id: int, sent: int, failed: int):
    now = datetime.now().isoformat(timespec="seconds")
    conn.execute("""
    UPDATE broadcasts SET status='sent', sent_at=?, sent_count=?, fail_count=?
    WHERE id=?
    """, (now, sent, failed, broadcast_id))
    conn.commit()


def get_broadcast_history(limit: int = 20):
    return conn.execute("""
    SELECT * FROM broadcasts ORDER BY created_at DESC LIMIT ?
    """, (limit,)).fetchall()


def get_scheduled_broadcasts():
    """Все запланированные (ещё не отправленные) рассылки."""
    return conn.execute("""
    SELECT * FROM broadcasts
    WHERE status='pending' AND scheduled_at IS NOT NULL
    ORDER BY scheduled_at ASC
    """).fetchall()


def cancel_broadcast(broadcast_id: int):
    conn.execute("UPDATE broadcasts SET status='cancelled' WHERE id=?", (broadcast_id,))
    conn.commit()
