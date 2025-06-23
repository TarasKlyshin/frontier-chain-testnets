from fastapi import FastAPI, Request, Form
from fastapi.templating import Jinja2Templates
from fastapi.responses import RedirectResponse
import sqlite3
from telegram import Bot

app = FastAPI()
templates = Jinja2Templates(directory="templates")

# Telegram Bot Token
TOKEN = "7714342405:AAEoia1V49MD6pf5j31RQM5tQxf0nE--83U"
bot = Bot(token=TOKEN)

def fetch_requests(status_filter=None):
    """ Получает список всех заявок с именами пользователей и их компаниями. """
    conn = sqlite3.connect("db.sqlite3")
    cur = conn.cursor()
    
    query = """
        SELECT r.id, r.user_id, COALESCE(u.name, 'Неизвестный'), COALESCE(u.company, 'Не указана'),
               r.problem, r.created_at, r.status, COALESCE(r.assigned_to, 'Не назначен')
        FROM requests r
        LEFT JOIN users u ON r.user_id = u.id
    """
    
    if status_filter:
        query += " WHERE r.status = ? ORDER BY r.created_at DESC"
        cur.execute(query, (status_filter,))
    else:
        query += " ORDER BY r.created_at DESC"
        cur.execute(query)
    
    rows = cur.fetchall()
    conn.close()
    return [
        {
            "id": r[0], "user_id": r[1], "name": r[2], "company": r[3],
            "problem": r[4], "created_at": r[5], "status": r[6], "assigned_to": r[7]
        }
        for r in rows
    ]

def get_request(request_id):
    """ Получает данные по одной заявке (по её ID). """
    conn = sqlite3.connect("db.sqlite3")
    cur = conn.cursor()
    cur.execute("""
        SELECT r.id, r.user_id, COALESCE(u.name, 'Неизвестный'), COALESCE(u.company, 'Не указана'),
               r.problem, r.created_at, r.status, COALESCE(r.assigned_to, 'Не назначен')
        FROM requests r
        LEFT JOIN users u ON r.user_id = u.id
        WHERE r.id = ?
    """, (request_id,))
    row = cur.fetchone()
    conn.close()
    if row:
        return {
            "id": row[0], "user_id": row[1], "name": row[2], "company": row[3],
            "problem": row[4], "created_at": row[5], "status": row[6], "assigned_to": row[7]
        }
    return None

def update_request_status(request_id, new_status):
    """ Обновляет статус заявки. """
    conn = sqlite3.connect("db.sqlite3")
    cur = conn.cursor()
    cur.execute("UPDATE requests SET status = ? WHERE id = ?", (new_status, request_id))
    conn.commit()
    conn.close()

def assign_request(request_id, executor_id, executor_chat_id):
    """ Назначает заявку исполнителю и отправляет уведомление. """
    conn = sqlite3.connect("db.sqlite3")
    cur = conn.cursor()
    cur.execute("UPDATE requests SET assigned_to = ? WHERE id = ?", (executor_id, request_id))
    conn.commit()
    conn.close()

    send_request_notification(request_id, executor_chat_id)

def send_request_notification(request_id, executor_chat_id):
    """ Отправляет детальное уведомление исполнителю через Telegram. """
    request_data = get_request(request_id)

    if not request_data:
        bot.send_message(chat_id=executor_chat_id, text=f"❌ Ошибка: данные заявки #{request_id} не найдены.")
        return
    
    # Если описание пустое, подставляем заглушку "Описание не указано"
    problem_text = request_data['problem'] if request_data['problem'] else "Описание не указано"

    message = (
        f"📝 Вам назначена заявка #{request_data['id']}\n"
        f"👤 От пользователя: {request_data['name']} ({request_data['company']})\n"
        f"📅 Дата создания: {request_data['created_at']}\n"
        f"⚙️ Статус: {request_data['status']}\n"
        f"💬 Описание проблемы:\n{problem_text}"
    )

    print("Отправляемое сообщение:", message)  # Проверяем перед отправкой
    bot.send_message(chat_id=executor_chat_id, text=message)

# Главная страница
@app.get("/")
def index(request: Request, status: str = None):
    requests_data = fetch_requests(status_filter=status)
    return templates.TemplateResponse("index.html", {"request": request, "requests": requests_data, "status_filter": status})

# Страница конкретной заявки
@app.get("/request/{request_id}")
def request_details(request: Request, request_id: int):
    request_data = get_request(request_id)
    if request_data:
        return templates.TemplateResponse("request.html", {"request": request, "req": request_data})
    return RedirectResponse(url="/")

# Обновление статуса заявки
@app.post("/request/{request_id}/update_status")
def update_status(request_id: int, status: str = Form(...)):
    update_request_status(request_id, status)
    return RedirectResponse(url=f"/request/{request_id}")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)