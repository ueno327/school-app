import os
import sqlite3
import shutil
from datetime import datetime
from fastapi import FastAPI, Request, Form, File, UploadFile
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from fastapi.staticfiles import StaticFiles
from starlette.middleware.sessions import SessionMiddleware

app = FastAPI()

# セッションの設定
app.add_middleware(SessionMiddleware, secret_key="your-secret-key-final-999")

# テンプレートと画像保存先の設定
templates = Jinja2Templates(directory="templates")
UPLOAD_DIR = "static/uploads"
os.makedirs(UPLOAD_DIR, exist_ok=True)
app.mount("/static", StaticFiles(directory="static"), name="static")

# --- データベース初期化 ---
def init_db():
    conn = sqlite3.connect("sns_app.db")
    cursor = conn.cursor()
    # ユーザーテーブル
    cursor.execute("CREATE TABLE IF NOT EXISTS users (username TEXT PRIMARY KEY, password TEXT)")
    # 投稿テーブル
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS events (
            id INTEGER PRIMARY KEY AUTOINCREMENT, 
            date TEXT, 
            user TEXT, 
            title TEXT, 
            likes INTEGER DEFAULT 0,
            image_url TEXT
        )
    """)
    # いいね記録
    cursor.execute("CREATE TABLE IF NOT EXISTS likes_record (username TEXT, event_id INTEGER, PRIMARY KEY (username, event_id))")
    
    # 【ここに修正！】コメントテーブル作成を init_db に移動しました
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS comments (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            event_id INTEGER,
            user TEXT,
            text TEXT,
            date TEXT
        )
    """)
    conn.commit()
    conn.close()

# 起動時に必ず実行（カッコを付けました）
init_db()

def get_current_user(request: Request):
    return request.session.get("user")

# --- ルーティング ---

@app.get("/", response_class=HTMLResponse)
async def read_index(request: Request):
    user = get_current_user(request)
    conn = sqlite3.connect("sns_app.db")
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    
    # 投稿を取得
    cursor.execute("SELECT * FROM events ORDER BY id DESC")
    db_events = [dict(row) for row in cursor.fetchall()]
    
    # 各投稿に紐づくコメントを取得して合体させる
    for event in db_events:
        cursor.execute("SELECT * FROM comments WHERE event_id = ? ORDER BY id ASC", (event["id"],))
        event["comments"] = cursor.fetchall()
        
    conn.close()
    return templates.TemplateResponse("index.html", {"request": request, "events": db_events, "current_user": user})

@app.post("/register")
async def register(username: str = Form(...), password: str = Form(...)):
    conn = sqlite3.connect("sns_app.db")
    cursor = conn.cursor()
    try:
        cursor.execute("INSERT INTO users (username, password) VALUES (?, ?)", (username, password))
        conn.commit()
    except:
        return "その名前は使用できません"
    finally:
        conn.close()
    return RedirectResponse(url="/", status_code=303)

@app.post("/login")
async def login(request: Request, username: str = Form(...), password: str = Form(...)):
    conn = sqlite3.connect("sns_app.db")
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM users WHERE username = ? AND password = ?", (username, password))
    user = cursor.fetchone()
    conn.close()
    if user:
        request.session["user"] = username
        return RedirectResponse(url="/", status_code=303)
    return "ログイン失敗"

@app.get("/logout")
async def logout(request: Request):
    request.session.pop("user", None)
    return RedirectResponse(url="/")

@app.post("/add_event")
async def add_event(request: Request, title: str = Form(...), event_date: str = Form(...), image: UploadFile = File(None)):
    user = get_current_user(request)
    if not user: return RedirectResponse(url="/", status_code=303)
    
    image_url = ""
    if image and image.filename:
        file_path = os.path.join(UPLOAD_DIR, image.filename)
        with open(file_path, "wb") as buffer:
            shutil.copyfileobj(image.file, buffer)
        image_url = f"/static/uploads/{image.filename}"

    conn = sqlite3.connect("sns_app.db")
    cursor = conn.cursor()
    cursor.execute("INSERT INTO events (date, user, title, likes, image_url) VALUES (?, ?, ?, ?, ?)", (event_date, user, title, 0, image_url))
    conn.commit()
    conn.close()
    return RedirectResponse(url="/", status_code=303)

@app.post("/like/{event_id}")
async def like_event(request: Request, event_id: int):
    user = get_current_user(request)
    if not user: return RedirectResponse(url="/", status_code=303)
    conn = sqlite3.connect("sns_app.db")
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM likes_record WHERE username = ? AND event_id = ?", (user, event_id))
    if cursor.fetchone():
        cursor.execute("DELETE FROM likes_record WHERE username = ? AND event_id = ?", (user, event_id))
        cursor.execute("UPDATE events SET likes = likes - 1 WHERE id = ?", (event_id,))
    else:
        cursor.execute("INSERT INTO likes_record (username, event_id) VALUES (?, ?)", (user, event_id))
        cursor.execute("UPDATE events SET likes = likes + 1 WHERE id = ?", (event_id,))
    conn.commit()
    conn.close()
    return RedirectResponse(url="/", status_code=303)

@app.post("/delete/{event_id}")
async def delete_event(request: Request, event_id: int):
    user = get_current_user(request)
    if not user: return RedirectResponse(url="/", status_code=303)

    conn = sqlite3.connect("sns_app.db")
    cursor = conn.cursor()
    
    cursor.execute("SELECT user, image_url FROM events WHERE id = ?", (event_id,))
    event = cursor.fetchone()

    if event and event[0] == user:
        if event[1]:
            img_path = event[1].lstrip("/")
            if os.path.exists(img_path):
                os.remove(img_path)
        
        cursor.execute("DELETE FROM events WHERE id = ?", (event_id,))
        cursor.execute("DELETE FROM likes_record WHERE event_id = ?", (event_id,))
        cursor.execute("DELETE FROM comments WHERE event_id = ?", (event_id,))
        conn.commit()
    
    conn.close()
    return RedirectResponse(url="/", status_code=303)

@app.post("/comment/{event_id}")
async def add_comment(request: Request, event_id: int, text: str = Form(...)):
    user = get_current_user(request)
    if not user: return RedirectResponse(url="/", status_code=303)
    
    conn = sqlite3.connect("sns_app.db")
    cursor = conn.cursor()
    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    cursor.execute("INSERT INTO comments (event_id, user, text, date) VALUES (?, ?, ?, ?)", 
                   (event_id, user, text, now))
    conn.commit()
    conn.close()
    return RedirectResponse(url="/", status_code=303)