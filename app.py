import os
import sqlite3
import uuid
from datetime import timedelta
from functools import wraps

from flask import Flask, abort, g, jsonify, redirect, request, send_from_directory, session
from google.auth.transport
import requests as google_requests
from google.oauth2 import id_token
from werkzeug.security import check_password_hash, generate_password_hash

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# Публичная часть сайта (на сервере её отдаёт nginx, тут — для локального теста)
SITE_DIR = os.path.join(BASE_DIR, "static", "web")

# Картинки новостей, загруженные из админки (отдаются nginx как /uploads/...)
UPLOAD_DIR = os.path.join(SITE_DIR, "uploads")
ALLOWED_EXT = {"png", "jpg", "jpeg", "webp", "gif"}

# Закрытые страницы — ВНЕ static/, nginx их напрямую не отдаёт
PRIVATE_DIR = os.path.join(BASE_DIR, "private")

DB_PATH = os.path.join(BASE_DIR, "users.db")

# Client ID из Google Cloud Console (задаётся в сервисе systemd)
GOOGLE_CLIENT_ID = os.environ.get("GOOGLE_CLIENT_ID", "")
_google_request = google_requests.Request()

app = Flask(__name__, static_folder=SITE_DIR, static_url_path="")
app.secret_key = os.environ.get("SECRET_KEY", "dev-only-change-me")
app.permanent_session_lifetime = timedelta(days=30)
app.config["MAX_CONTENT_LENGTH"] = 10 * 1024 * 1024  # 10 МБ на загрузку

os.makedirs(UPLOAD_DIR, exist_ok=True)


# ---------- База данных ----------

def get_db():
    if "db" not in g:
        g.db = sqlite3.connect(DB_PATH, timeout=10)
        g.db.row_factory = sqlite3.Row
    return g.db


@app.teardown_appcontext
def close_db(exc):
    db = g.pop("db", None)
    if db is not None:
        db.close()


# Новости, которые уже были на сайте — попадут в базу при первом запуске.
# Порядок: первая в списке окажется внизу страницы.
SEED_NEWS = [
    ("Zināšanu diena", "2026. gada 1. septembris", "", "images/zin.png"),
    ("Literatūras saraksts vasaras lasīšanai", "", "", "images/literatura_2026a.png"),
    ("Uzņēmuma diena", "", "", "images/ielug_2026.png"),
]


def init_db():
    # EXCLUSIVE — чтобы два воркера gunicorn не создали/заполнили таблицы одновременно
    conn = sqlite3.connect(DB_PATH, timeout=10, isolation_level=None)
    try:
        conn.execute("BEGIN EXCLUSIVE")

        conn.execute("""
            CREATE TABLE IF NOT EXISTS users (
                id            INTEGER PRIMARY KEY AUTOINCREMENT,
                username      TEXT UNIQUE NOT NULL,
                email         TEXT UNIQUE NOT NULL,
                password_hash TEXT NOT NULL,
                is_admin      INTEGER NOT NULL DEFAULT 0,
                google_sub    TEXT,
                created_at    TEXT DEFAULT CURRENT_TIMESTAMP
            )
        """)
        cols = [row[1] for row in conn.execute("PRAGMA table_info(users)")]
        if "is_admin" not in cols:
            conn.execute("ALTER TABLE users ADD COLUMN is_admin INTEGER NOT NULL DEFAULT 0")
        if "google_sub" not in cols:
            conn.execute("ALTER TABLE users ADD COLUMN google_sub TEXT")
        # один Google-аккаунт = один пользователь сайта
        conn.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_users_google_sub ON users(google_sub)")

        conn.execute("""
            CREATE TABLE IF NOT EXISTS news (
                id         INTEGER PRIMARY KEY AUTOINCREMENT,
                title      TEXT NOT NULL,
                date_text  TEXT NOT NULL DEFAULT '',
                body       TEXT NOT NULL DEFAULT '',
                image      TEXT NOT NULL DEFAULT '',
                created_at TEXT DEFAULT CURRENT_TIMESTAMP
            )
        """)
        if conn.execute("SELECT COUNT(*) FROM news").fetchone()[0] == 0:
            conn.executemany(
                "INSERT INTO news (title, date_text, body, image) VALUES (?, ?, ?, ?)",
                SEED_NEWS,
            )

        conn.execute("COMMIT")
    except Exception:
        conn.execute("ROLLBACK")
        raise
    finally:
        conn.close()


init_db()


def current_user():
    """Текущий пользователь из базы (или None). Права всегда берутся из БД."""
    user_id = session.get("user_id")
    if user_id is None:
        return None
    return get_db().execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()


def admin_required(view):
    @wraps(view)
    def wrapper(*args, **kwargs):
        user = current_user()
        if user is None or not user["is_admin"]:
            if request.path.startswith("/api/"):
                abort(403)
            return redirect("/")
        return view(*args, **kwargs)
    return wrapper


# ---------- Картинки ----------

def save_image(file):
    """Сохраняет загруженную картинку под случайным именем. Возвращает путь вида uploads/xxx.png."""
    if file is None or not file.filename:
        return None
    ext = file.filename.rsplit(".", 1)[-1].lower() if "." in file.filename else ""
    if ext not in ALLOWED_EXT:
        raise ValueError("Image must be PNG, JPG, WEBP or GIF")
    name = f"{uuid.uuid4().hex}.{ext}"
    file.save(os.path.join(UPLOAD_DIR, name))
    return f"uploads/{name}"


def delete_upload(path):
    """Удаляет файл, только если он из uploads/ (картинки из images/ не трогаем)."""
    if path and path.startswith("uploads/"):
        try:
            os.remove(os.path.join(SITE_DIR, path))
        except FileNotFoundError:
            pass


@app.errorhandler(413)
def too_large(err):
    return jsonify(ok=False, error="Image is too large (max 10 MB)"), 413


# ---------- Страницы ----------

@app.route("/")
def index():
    return send_from_directory(SITE_DIR, "index.html")


@app.route("/admin")
@admin_required
def admin_page():
    resp = send_from_directory(PRIVATE_DIR, "admin.html")
    resp.headers["Cache-Control"] = "no-store"  # чтобы Cloudflare/браузер не кэшировали
    return resp


# ---------- API: аккаунт ----------

@app.post("/api/register")
def api_register():
    data = request.get_json(silent=True) or {}
    uname = data.get("uname", "").strip()
    email = data.get("email", "").strip().lower()
    psw = data.get("psw", "")

    if not uname or not email or len(psw) < 6:
        return jsonify(ok=False, error="Fill in all fields, password min 6 chars"), 400

    db = get_db()
    try:
        cur = db.execute(
            "INSERT INTO users (username, email, password_hash) VALUES (?, ?, ?)",
            (uname, email, generate_password_hash(psw)),
        )
        db.commit()
    except sqlite3.IntegrityError:
        return jsonify(ok=False, error="Username or email already taken"), 409

    session.clear()
    session["user_id"] = cur.lastrowid
    return jsonify(ok=True, username=uname, is_admin=False)


@app.post("/api/login")
def api_login():
    data = request.get_json(silent=True) or {}
    uname = data.get("uname", "").strip()
    psw = data.get("psw", "")

    user = get_db().execute(
        "SELECT * FROM users WHERE username = ?", (uname,)
    ).fetchone()

    if user is None or not check_password_hash(user["password_hash"], psw):
        return jsonify(ok=False, error="Wrong username or password"), 401

    session.clear()
    session.permanent = bool(data.get("remember"))
    session["user_id"] = user["id"]
    return jsonify(ok=True, username=user["username"], is_admin=bool(user["is_admin"]))


def unique_username(db, base):
    """Имя для нового Google-пользователя: из почты, без пробелов; если занято — добавляем цифру."""
    base = "".join(ch for ch in base if ch.isalnum() or ch in "._-")[:30] or "user"
    name, n = base, 1
    while db.execute("SELECT 1 FROM users WHERE username = ?", (name,)).fetchone():
        n += 1
        name = f"{base}{n}"
    return name


@app.post("/api/auth/google")
def api_auth_google():
    if not GOOGLE_CLIENT_ID:
        return jsonify(ok=False, error="Google sign-in is not configured"), 500

    token = (request.get_json(silent=True) or {}).get("credential", "")
    try:
        # Проверяет подпись Google, срок действия и что токен выдан именно нашему сайту
        info = id_token.verify_oauth2_token(token, _google_request, GOOGLE_CLIENT_ID)
    except ValueError:
        return jsonify(ok=False, error="Google sign-in failed, try again"), 401

    if not info.get("email_verified"):
        return jsonify(ok=False, error="This Google account has no verified email"), 400

    sub = info["sub"]                      # постоянный id аккаунта Google
    email = info["email"].strip().lower()

    db = get_db()
    user = db.execute("SELECT * FROM users WHERE google_sub = ?", (sub,)).fetchone()

    if user is None:
        user = db.execute("SELECT * FROM users WHERE email = ?", (email,)).fetchone()
        if user is not None:
            # уже был аккаунт с этой почтой — привязываем к нему Google
            db.execute("UPDATE users SET google_sub = ? WHERE id = ?", (sub, user["id"]))
        else:
            # новый пользователь; пароля нет — войти можно только через Google
            username = unique_username(db, email.split("@")[0])
            cur = db.execute(
                "INSERT INTO users (username, email, password_hash, google_sub) VALUES (?, ?, '', ?)",
                (username, email, sub),
            )
            user = db.execute("SELECT * FROM users WHERE id = ?", (cur.lastrowid,)).fetchone()
        db.commit()

    session.clear()
    session.permanent = True
    session["user_id"] = user["id"]
    return jsonify(ok=True, username=user["username"], is_admin=bool(user["is_admin"]))


@app.get("/api/me")
def api_me():
    user = current_user()
    if user is None:
        return jsonify(id=None, username=None, is_admin=False)
    return jsonify(id=user["id"], username=user["username"], is_admin=bool(user["is_admin"]))


@app.get("/api/config")
def api_config():
    """Публичные настройки для фронтенда (Client ID не секретный)."""
    return jsonify(google_client_id=GOOGLE_CLIENT_ID or None)


@app.post("/api/logout")
def api_logout():
    session.clear()
    return jsonify(ok=True)


# ---------- API: новости (публичное чтение) ----------

@app.get("/api/news")
def api_news():
    rows = get_db().execute(
        "SELECT id, title, date_text, body, image FROM news ORDER BY id DESC"
    ).fetchall()
    resp = jsonify([dict(r) for r in rows])
    resp.headers["Cache-Control"] = "no-store"
    return resp


# ---------- API для админов: пользователи ----------

@app.get("/api/admin/users")
@admin_required
def api_admin_users():
    rows = get_db().execute(
        "SELECT id, username, email, is_admin, created_at FROM users ORDER BY id"
    ).fetchall()
    return jsonify([dict(r) for r in rows])


@app.post("/api/admin/users/<int:uid>/admin")
@admin_required
def api_admin_set_role(uid):
    if uid == session.get("user_id"):
        return jsonify(ok=False, error="You can't change your own admin access"), 400

    data = request.get_json(silent=True) or {}
    value = 1 if data.get("is_admin") else 0

    db = get_db()
    cur = db.execute("UPDATE users SET is_admin = ? WHERE id = ?", (value, uid))
    db.commit()
    if cur.rowcount == 0:
        return jsonify(ok=False, error="User not found"), 404
    return jsonify(ok=True)


@app.delete("/api/admin/users/<int:uid>")
@admin_required
def api_admin_delete_user(uid):
    if uid == session.get("user_id"):
        return jsonify(ok=False, error="You can't delete your own account here"), 400

    db = get_db()
    cur = db.execute("DELETE FROM users WHERE id = ?", (uid,))
    db.commit()
    if cur.rowcount == 0:
        return jsonify(ok=False, error="User not found"), 404
    return jsonify(ok=True)


# ---------- API для админов: новости ----------

def news_fields():
    return (
        request.form.get("title", "").strip(),
        request.form.get("date_text", "").strip(),
        request.form.get("body", "").strip(),
    )


@app.post("/api/admin/news")
@admin_required
def api_admin_news_create():
    title, date_text, body = news_fields()
    if not title:
        return jsonify(ok=False, error="Title is required"), 400

    try:
        image = save_image(request.files.get("image"))
    except ValueError as e:
        return jsonify(ok=False, error=str(e)), 400

    db = get_db()
    cur = db.execute(
        "INSERT INTO news (title, date_text, body, image) VALUES (?, ?, ?, ?)",
        (title, date_text, body, image or ""),
    )
    db.commit()
    return jsonify(ok=True, id=cur.lastrowid)


@app.post("/api/admin/news/<int:nid>")
@admin_required
def api_admin_news_update(nid):
    db = get_db()
    row = db.execute("SELECT * FROM news WHERE id = ?", (nid,)).fetchone()
    if row is None:
        return jsonify(ok=False, error="News not found"), 404

    title, date_text, body = news_fields()
    if not title:
        return jsonify(ok=False, error="Title is required"), 400

    try:
        new_image = save_image(request.files.get("image"))
    except ValueError as e:
        return jsonify(ok=False, error=str(e)), 400

    image = row["image"]
    if new_image:
        delete_upload(image)      # старая картинка больше не нужна
        image = new_image

    db.execute(
        "UPDATE news SET title = ?, date_text = ?, body = ?, image = ? WHERE id = ?",
        (title, date_text, body, image, nid),
    )
    db.commit()
    return jsonify(ok=True)


@app.delete("/api/admin/news/<int:nid>")
@admin_required
def api_admin_news_delete(nid):
    db = get_db()
    row = db.execute("SELECT image FROM news WHERE id = ?", (nid,)).fetchone()
    if row is None:
        return jsonify(ok=False, error="News not found"), 404

    db.execute("DELETE FROM news WHERE id = ?", (nid,))
    db.commit()
    delete_upload(row["image"])
    return jsonify(ok=True)


if __name__ == "__main__":
    app.run(debug=True)