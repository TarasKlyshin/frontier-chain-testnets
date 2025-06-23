import re
import sqlite3
import threading
import time
from datetime import datetime, timedelta

from telegram import (
    Update,
    ReplyKeyboardMarkup,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    ReplyKeyboardRemove
)
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    filters,
    ContextTypes
)
from telegram.error import BadRequest

# Database initialization
DB_PATH = "db.sqlite3"

def init_db():
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    # Users table
    cur.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY,
            name TEXT,
            company TEXT,
            phone TEXT,
            first_seen TEXT
        )""")
    # Requests table with cancel reason
    cur.execute("""
        CREATE TABLE IF NOT EXISTS requests (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            problem TEXT,
            priority TEXT,
            created_at TEXT,
            status TEXT DEFAULT 'Новая',
            assigned_to TEXT,
            cancel_reason TEXT,
            FOREIGN KEY(user_id) REFERENCES users(id)
        )""")
    conn.commit()
    conn.close()

init_db()

# Constants
GROUP_CHAT_ID = -1002692729010
OVERDUE_DAYS = 3
SCHEDULER_INTERVAL = 3600
TOKEN = "7714342405:AAEoia1V49MD6pf5j31RQM5tQxf0nE--83U"

# Executors mapping
executors = {
    "374534910": "Клышин",
    "560722677": "Гриднев",
    "412384604": "Оралбаев",
    "289862774": "Филимонов"
}

# Conversation states and temporary stores
states = {
    'report': {},
    'cancel': {}
}
photo_store = {}
request_messages = {}

# Keyboard definitions
main_menu = ReplyKeyboardMarkup(
    [["📋 Оставить заявку", "ℹ️ О нас"], ["📊 Статистика", "❓ FAQ"]],
    resize_keyboard=True
)
priority_kb = ReplyKeyboardMarkup(
    [["Низкий", "Средний", "Высокий"]],
    one_time_keyboard=True,
    resize_keyboard=True
)
yesno_kb = ReplyKeyboardMarkup(
    [["Да", "Нет"]],
    one_time_keyboard=True,
    resize_keyboard=True
)

# Database utilities
def insert_user(user_id: int, name: str, company: str, phone: str):
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute(
        "INSERT OR REPLACE INTO users (id, name, company, phone, first_seen)"
        " VALUES (?, ?, ?, ?, datetime('now'))",
        (user_id, name, company, phone)
    )
    conn.commit()
    conn.close()

def insert_request(user_id: int, problem: str, priority: str) -> int:
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute(
        "INSERT INTO requests (user_id, problem, priority, created_at)"
        " VALUES (?, ?, ?, datetime('now'))",
        (user_id, problem, priority)
    )
    req_id = cur.lastrowid
    conn.commit()
    conn.close()
    return req_id

# Helpers
def validate_phone(phone: str) -> bool:
    return bool(re.match(r"^(?:\+7|8)7\d{9}$", phone))

# Command handlers
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Привет! Выберите действие:", reply_markup=main_menu)

async def about_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "ℹ️ Бот для регистрации заявок: собирает имя, фирму, телефон, приоритет и фото.",
        reply_markup=main_menu
    )

async def stats_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("SELECT status, COUNT(*) FROM requests GROUP BY status")
    rows = cur.fetchall()
    conn.close()
    text = "📊 Статистика заявок:\n"
    for status, cnt in rows:
        text += f"{status}: {cnt}\n"
    await update.message.reply_text(text, reply_markup=main_menu)

async def faq_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = (
        "❓ FAQ:\n"
        "1. Чтобы оставить заявку — нажмите '📋 Оставить заявку'.\n"
        "2. Чтобы посмотреть статистику — '📊 Статистика'.\n"
        "3. О боте — 'ℹ️ О нас'."
    )
    await update.message.reply_text(text, reply_markup=main_menu)

# Report flow
async def report_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.message.from_user.id
    states['report'][uid] = {'step': 0}
    await update.message.reply_text("Как вас зовут?", reply_markup=ReplyKeyboardRemove())

async def process_report_flow(update: Update, context: ContextTypes.DEFAULT_TYPE, st):
    uid = update.message.from_user.id
    text = update.message.text.strip()
    step = st['step']
    if step == 0:
        st['name'], st['step'] = text, 1
        return await update.message.reply_text("Из какой вы фирмы?")
    if step == 1:
        st['company'], st['step'] = text, 2
        return await update.message.reply_text("Введите телефон (пример +77001234567)")
    if step == 2:
        if not validate_phone(text):
            return await update.message.reply_text("Некорректный номер. Пример +77001234567")
        st['phone'], st['step'] = text, 3
        return await update.message.reply_text("Опишите проблему:")
    if step == 3:
        st['problem'], st['step'] = text, 4
        return await update.message.reply_text("Укажите приоритет:", reply_markup=priority_kb)
    if step == 4:
        pr = text.capitalize()
        if pr not in ("Низкий", "Средний", "Высокий"):
            return await update.message.reply_text("Выберите приоритет кнопками.")
        st['priority'], st['step'] = pr, 5
        return await update.message.reply_text("Добавить фото к заявке?", reply_markup=yesno_kb)
    if step == 5:
        if text == "Да":
            st['step'] = 6
            photo_store[uid] = []
            ready_btn = InlineKeyboardMarkup([[InlineKeyboardButton("Готово", callback_data="ready")]])
            return await update.message.reply_text("Прикрепите фото, затем нажмите Готово", reply_markup=ready_btn)
        return await finish_request(update, context, st)

async def finish_request(update: Update, context: ContextTypes.DEFAULT_TYPE, st):
    uid = update.message.from_user.id if update.message else update.callback_query.from_user.id
    insert_user(uid, st['name'], st['company'], st['phone'])
    req_id = insert_request(uid, st['problem'], st['priority'])

    text_msg = (
        f"📥 Новая заявка #{req_id}\n"
        f"👤 Имя: {st['name']}\n"
        f"🏢 Компания: {st['company']}\n"
        f"📞 Телефон: {st['phone']}\n"
        f"⚡ Приоритет: {st['priority']}\n"
        f"💬 Проблема: {st['problem']}"
    )
    buttons = [
        [InlineKeyboardButton("👤 Клышин", callback_data=f"assign:{req_id}:374534910"), InlineKeyboardButton("👤 Гриднев", callback_data=f"assign:{req_id}:560722677")],
        [InlineKeyboardButton("👤 Оралбаев", callback_data=f"assign:{req_id}:412384604"), InlineKeyboardButton("👤 Филимонов", callback_data=f"assign:{req_id}:289862774")]
    ]
    markup = InlineKeyboardMarkup(buttons)
    msg = await context.bot.send_message(chat_id=GROUP_CHAT_ID, text=text_msg, reply_markup=markup)
    request_messages[req_id] = msg.message_id
    for ph in photo_store.get(uid, []):
        await context.bot.send_photo(chat_id=GROUP_CHAT_ID, photo=ph)
    photo_store.pop(uid, None)
    states['report'].pop(uid, None)
    await context.bot.send_message(chat_id=uid, text=f"Заявка #{req_id} создана.", reply_markup=main_menu)

async def photo_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.message.from_user.id
    if uid in states['report'] and states['report'][uid]['step'] == 6:
        photo_id = update.message.photo[-1].file_id
        photo_store.setdefault(uid, []).append(photo_id)
        return await update.message.reply_text("Фото получено. Прикрепите ещё или нажмите Готово.")

async def ready_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    uid = query.from_user.id
    if uid in states['report'] and states['report'][uid]['step'] == 6:
        return await finish_request(update, context, states['report'][uid])

async def echo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.message.from_user.id
    if uid in states['report']:
        return await process_report_flow(update, context, states['report'][uid])
    text = update.message.text.strip() if update.message.text else ''
    if text == "📋 Оставить заявку":
        return await report_command(update, context)
    if text == "ℹ️ О нас":
        return await about_command(update, context)
    if text == "📊 Статистика":
        return await stats_command(update, context)
    if text == "❓ FAQ":
        return await faq_command(update, context)

async def handle_assignment(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    _, req_id, exec_id = query.data.split(":")
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("UPDATE requests SET assigned_to=? WHERE id=?", (executors[exec_id], req_id))
    conn.commit()
    conn.close()
    buttons = [[InlineKeyboardButton("🕒 В работе", callback_data=f"action:work:{req_id}")]]
    await context.bot.edit_message_text(
        chat_id=GROUP_CHAT_ID,
        message_id=request_messages[int(req_id)],
        text=f"Заявка #{req_id} назначена: {executors[exec_id]}",
        reply_markup=InlineKeyboardMarkup(buttons)
    )

async def handle_action(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    _, action, req_id = query.data.split(":")
    if action == "work":
        conn = sqlite3.connect(DB_PATH)
        cur = conn.cursor()
        cur.execute("UPDATE requests SET status='В работе' WHERE id=?", (req_id,))
        conn.commit()
        conn.close()
        buttons = [[InlineKeyboardButton("✅ Завершить", callback_data=f"action:finish:{req_id}"), InlineKeyboardButton("🔄 Изменить статус", callback_data=f"action:status:{req_id}")]]
        await context.bot.edit_message_reply_markup(chat_id=GROUP_CHAT_ID, message_id=request_messages[int(req_id)], reply_markup=InlineKeyboardMarkup(buttons))
    elif action == "finish":
        conn = sqlite3.connect(DB_PATH)
        cur = conn.cursor()
        cur.execute("UPDATE requests SET status='Завершена' WHERE id=?", (req_id,))
        conn.commit()
        conn.close()
        await context.bot.send_message(GROUP_CHAT_ID, f"Заявка #{req_id} успешно завершена.")
    elif action == "status":
        buttons = [[InlineKeyboardButton("В работе", callback_data=f"action:work:{req_id}"), InlineKeyboardButton("Завершена", callback_data=f"action:finish:{req_id}"), InlineKeyboardButton("Отклонена", callback_data=f"action:cancel:{req_id}")]]
        await context.bot.edit_message_reply_markup(chat_id=GROUP_CHAT_ID, message_id=request_messages[int(req_id)], reply_markup=InlineKeyboardMarkup(buttons))
    elif action == "cancel":
        uid = update.callback_query.from_user.id
        states['cancel'][uid] = req_id
        await context.bot.send_message(uid, f"Введите причину отклонения заявки #{req_id}:")

async def cancel_reason_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.message.from_user.id
    if uid in states['cancel']:
        req_id = states['cancel'].pop(uid)
        reason = update.message.text.strip()
        conn = sqlite3.connect(DB_PATH)
        cur = conn.cursor()
        cur.execute("UPDATE requests SET status='Отклонена', cancel_reason=? WHERE id=?", (reason, req_id))
        conn.commit()
        conn.close()
        await update.message.reply_text(f"Причина отклонения заявки #{req_id} сохранена.")

# Scheduler for overdue notifications
def schedule_overdue(app):
    def job():
        while True:
            conn = sqlite3.connect(DB_PATH)
            cur = conn.cursor()
            cutoff = datetime.now() - timedelta(days=OVERDUE_DAYS)
            cur.execute("SELECT id FROM requests WHERE status='В работе' AND datetime(created_at)<=?", (cutoff.strftime('%Y-%m-%d %H:%M:%S'),))
            for (rid,) in cur.fetchall():
                app.bot.send_message(GROUP_CHAT_ID, f"⚠️ Заявка #{rid} просрочена")
            conn.close()
            time.sleep(SCHEDULER_INTERVAL)
    threading.Thread(target=job, daemon=True).start()

# Run bot
app = ApplicationBuilder().token(TOKEN).build()
app.add_handler(CommandHandler("start", start, filters=filters.ChatType.PRIVATE))
app.add_handler(CommandHandler("report", report_command, filters=filters.ChatType.PRIVATE))
app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND & filters.ChatType.PRIVATE, echo))
app.add_handler(CallbackQueryHandler(ready_handler, pattern="^ready$"))
app.add_handler(CallbackQueryHandler(handle_assignment, pattern="^assign:"))
app.add_handler(CallbackQueryHandler(handle_action, pattern="^action:"))
app.add_handler(MessageHandler(filters.PHOTO & filters.ChatType.PRIVATE, photo_handler))
app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND & filters.ChatType.PRIVATE, cancel_reason_handler))
app.run_polling()
