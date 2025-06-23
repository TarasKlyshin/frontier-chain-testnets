import sqlite3
from datetime import datetime

DB_PATH = "db.sqlite3"

# Инициализация БД и создание таблиц при первом запуске
def _init_db():
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS users (
        id INTEGER PRIMARY KEY,
        name TEXT,
        company TEXT,
        phone TEXT,
        first_seen TEXT
    )
    """)
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS requests (
        id INTEGER PRIMARY KEY,
        user_id INTEGER,
        problem TEXT,
        created_at TEXT,
        status TEXT DEFAULT 'Новая',
        assigned_to TEXT,
        FOREIGN KEY(user_id) REFERENCES users(id)
    )
    """)
    conn.commit()
    conn.close()

# Вызываем инициализацию
_init_db()

def insert_user(user_id: int, name: str, company: str, phone: str):
    """
    Добавляет пользователя в таблицу users, если его там ещё нет.
    Возвращает user_id.
    """
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    # Проверяем, есть ли уже пользователь
    cursor.execute("SELECT id FROM users WHERE id = ?", (user_id,))
    if cursor.fetchone() is None:
        cursor.execute(
            "INSERT INTO users (id, name, company, phone, first_seen) VALUES (?, ?, ?, ?, datetime('now'))",
            (user_id, name, company, phone)
        )
        conn.commit()
    conn.close()
    return user_id

def insert_request(user_id: int, problem: str) -> int:
    """
    Создаёт новую заявку в таблице requests.
    Возвращает сгенерированный ID заявки.
    """
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute(
        "INSERT INTO requests (user_id, problem, created_at) VALUES (?, ?, datetime('now'))",
        (user_id, problem)
    )
    request_id = cursor.lastrowid
    conn.commit()
    conn.close()
    return request_id
