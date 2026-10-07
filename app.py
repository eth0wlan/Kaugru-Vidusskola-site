import os
import sqlite3
from datetime import timedelta

from flask import Flask, g, jsonify, request, send_from_directory, session
from werkzeug.security import check_password_hash, generate_password_hash

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# Папка, где лежит index.html (поменяй, если он в другом месте).
# Нужна только для локального теста — на сервере страницу отдаёт nginx.
SITE_DIR = os.path.join(BASE_DIR, "static", "web")

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
                created_at    TEXT DEFAULT CURRENT_TIMESTAMP
            )
        """)


init_db()  # выполняется и при python app.py, и под gunicorn


# ---------- Страница (только для локального теста) ----------

@app.route("/")
def index():
    return send_from_directory(SITE_DIR, "index.html")


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
        db.execute(
            "INSERT INTO users (username, email, password_hash) VALUES (?, ?, ?)",
            (uname, email, generate_password_hash(psw)),
        )
        db.commit()
    except sqlite3.IntegrityError:
        return jsonify(ok=False, error="Username or email already taken"), 409

    session["username"] = uname
    return jsonify(ok=True, username=uname)


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

    session.permanent = bool(data.get("remember"))
    session["username"] = user["username"]
    return jsonify(ok=True, username=user["username"])


@app.get("/api/me")
def api_me():
    return jsonify(username=session.get("username"))


@app.post("/api/logout")
def api_logout():
    session.clear()
    return jsonify(ok=True)


if __name__ == "__main__":
    app.run(debug=True)