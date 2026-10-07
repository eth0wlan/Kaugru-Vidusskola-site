import os
import sqlite3
from datetime import timedelta
from functools import wraps

from flask import Flask, abort, g, jsonify, redirect, request, send_from_directory, session
from werkzeug.security import check_password_hash, generate_password_hash

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# Публичная часть сайта (на сервере её отдаёт nginx, тут — для локального теста)
SITE_DIR = os.path.join(BASE_DIR, "static", "web")

# Закрытые страницы — ВНЕ static/, nginx их напрямую не отдаёт
PRIVATE_DIR = os.path.join(BASE_DIR, "private")

DB_PATH = os.path.join(BASE_DIR, "users.db")

app = Flask(__name__, static_folder=SITE_DIR, static_url_path="")
app.secret_key = os.environ.get("SECRET_KEY", "dev-only-change-me")
app.permanent_session_lifetime = timedelta(days=30)


# ---------- База данных ----------

def get_db():
    if "db" not in g:
        g.db = sqlite3.connect(DB_PATH)
        g.db.row_factory = sqlite3.Row
    return g.db


@app.teardown_appcontext
def close_db(exc):
    db = g.pop("db", None)
    if db is not None:
        db.close()


def init_db():
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS users (
                id            INTEGER PRIMARY KEY AUTOINCREMENT,
                username      TEXT UNIQUE NOT NULL,
                email         TEXT UNIQUE NOT NULL,
                password_hash TEXT NOT NULL,
                is_admin      INTEGER NOT NULL DEFAULT 0,
                created_at    TEXT DEFAULT CURRENT_TIMESTAMP
            )
        """)
        # Если таблица была создана раньше без is_admin — добавляем колонку
        cols = [row[1] for row in conn.execute("PRAGMA table_info(users)")]
        if "is_admin" not in cols:
            conn.execute("ALTER TABLE users ADD COLUMN is_admin INTEGER NOT NULL DEFAULT 0")


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


# ---------- API ----------

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


@app.get("/api/me")
def api_me():
    user = current_user()
    if user is None:
        return jsonify(id=None, username=None, is_admin=False)
    return jsonify(id=user["id"], username=user["username"], is_admin=bool(user["is_admin"]))


@app.post("/api/logout")
def api_logout():
    session.clear()
    return jsonify(ok=True)


# ---------- API для админов ----------

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


if __name__ == "__main__":
    app.run(debug=True)