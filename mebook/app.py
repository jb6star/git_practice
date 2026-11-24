"""Mebook - 내가 읽은 책을 쌓아 올리는 독서 기록 웹사이트."""

import calendar
import os
import secrets
import sqlite3
from datetime import date, datetime, timedelta
from functools import wraps

from flask import (
    Flask,
    abort,
    flash,
    g,
    redirect,
    render_template,
    request,
    session,
    url_for,
)
from werkzeug.security import check_password_hash, generate_password_hash

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
INSTANCE_DIR = os.path.join(BASE_DIR, "instance")
os.makedirs(INSTANCE_DIR, exist_ok=True)


def _load_secret_key():
    """환경변수 MEBOOK_SECRET_KEY 가 없으면 instance 폴더에 키를 만들어 재사용한다."""
    env_key = os.environ.get("MEBOOK_SECRET_KEY")
    if env_key:
        return env_key
    key_path = os.path.join(INSTANCE_DIR, "secret_key")
    if not os.path.exists(key_path):
        with open(key_path, "w") as f:
            f.write(secrets.token_hex(32))
    with open(key_path) as f:
        return f.read().strip()


app = Flask(__name__)
app.config.update(
    SECRET_KEY=_load_secret_key(),
    DATABASE=os.environ.get("MEBOOK_DB", os.path.join(INSTANCE_DIR, "mebook.db")),
    PERMANENT_SESSION_LIFETIME=timedelta(days=30),
)

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    username TEXT UNIQUE NOT NULL,
    password_hash TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS books (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    title TEXT NOT NULL,
    author TEXT NOT NULL DEFAULT '',
    cover_url TEXT NOT NULL DEFAULT '',
    finished_date TEXT,
    rating INTEGER NOT NULL DEFAULT 0,
    review TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_books_user_date ON books(user_id, finished_date);
CREATE TABLE IF NOT EXISTS attendance (
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    day TEXT NOT NULL,
    pages INTEGER NOT NULL DEFAULT 0,
    memo TEXT NOT NULL DEFAULT '',
    PRIMARY KEY (user_id, day)
);
"""

SPINE_COLORS = [
    "#c0392b", "#2c3e50", "#16a085", "#8e44ad", "#d35400",
    "#27ae60", "#2980b9", "#7f8c8d", "#b8860b", "#6d4c41",
    "#1e6f5c", "#a83279", "#34495e", "#e67e22",
]


# ---------------------------------------------------------------- DB helpers
def get_db():
    if "db" not in g:
        g.db = sqlite3.connect(app.config["DATABASE"])
        g.db.row_factory = sqlite3.Row
        g.db.execute("PRAGMA foreign_keys = ON")
    return g.db


@app.teardown_appcontext
def close_db(_exc):
    db = g.pop("db", None)
    if db is not None:
        db.close()


def init_db():
    db = sqlite3.connect(app.config["DATABASE"])
    db.executescript(SCHEMA)
    db.commit()
    db.close()


init_db()


def now_iso():
    return datetime.now().isoformat(timespec="seconds")


def parse_date(value):
    try:
        return datetime.strptime(value, "%Y-%m-%d").date()
    except (TypeError, ValueError):
        return None


# ---------------------------------------------------------------- auth / csrf
def login_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if g.user is None:
            return redirect(url_for("login", next=request.path))
        return view(*args, **kwargs)

    return wrapped


@app.before_request
def load_user_and_check_csrf():
    uid = session.get("user_id")
    g.user = None
    if uid is not None:
        g.user = get_db().execute(
            "SELECT id, username FROM users WHERE id = ?", (uid,)
        ).fetchone()
        if g.user is None:
            session.clear()

    if request.method == "POST":
        token = session.get("csrf_token")
        if not token or token != request.form.get("csrf_token"):
            abort(400, "잘못된 요청입니다. 페이지를 새로고침한 뒤 다시 시도해 주세요.")


@app.context_processor
def inject_globals():
    if "csrf_token" not in session:
        session["csrf_token"] = secrets.token_hex(16)
    return {"csrf_token": session["csrf_token"], "today": date.today()}


@app.template_filter("spine_color")
def spine_color(book_id):
    return SPINE_COLORS[(book_id or 0) % len(SPINE_COLORS)]


def safe_next(target):
    if target and target.startswith("/") and not target.startswith("//"):
        return target
    return url_for("shelf")


@app.route("/signup", methods=["GET", "POST"])
def signup():
    if g.user:
        return redirect(url_for("shelf"))
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")
        password2 = request.form.get("password2", "")
        error = None
        if not (2 <= len(username) <= 30):
            error = "아이디는 2~30자로 입력해 주세요."
        elif len(password) < 6:
            error = "비밀번호는 6자 이상이어야 해요."
        elif password != password2:
            error = "비밀번호 확인이 일치하지 않아요."
        if error is None:
            db = get_db()
            try:
                cur = db.execute(
                    "INSERT INTO users (username, password_hash, created_at) VALUES (?, ?, ?)",
                    (username, generate_password_hash(password), now_iso()),
                )
                db.commit()
            except sqlite3.IntegrityError:
                error = "이미 사용 중인 아이디예요."
            else:
                session.clear()
                session.permanent = True
                session["user_id"] = cur.lastrowid
                flash(f"{username}님, Mebook에 오신 걸 환영해요!")
                return redirect(url_for("shelf"))
        flash(error, "error")
    return render_template("auth.html", mode="signup")


@app.route("/login", methods=["GET", "POST"])
def login():
    if g.user:
        return redirect(url_for("shelf"))
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")
        user = get_db().execute(
            "SELECT * FROM users WHERE username = ?", (username,)
        ).fetchone()
        if user is None or not check_password_hash(user["password_hash"], password):
            flash("아이디 또는 비밀번호가 올바르지 않아요.", "error")
        else:
            session.clear()
            session.permanent = True
            session["user_id"] = user["id"]
            return redirect(safe_next(request.args.get("next")))
    return render_template("auth.html", mode="login")


@app.route("/logout", methods=["POST"])
def logout():
    session.clear()
    return redirect(url_for("login"))


# ---------------------------------------------------------------- shelf
def books_by_month(user_id, year):
    rows = get_db().execute(
        """SELECT * FROM books
           WHERE user_id = ? AND finished_date LIKE ?
           ORDER BY finished_date, id""",
        (user_id, f"{year}-%"),
    ).fetchall()
    months = {m: [] for m in range(1, 13)}
    for row in rows:
        months[int(row["finished_date"][5:7])].append(row)
    return months, rows


def months_elapsed(year):
    today = date.today()
    if year < today.year:
        return 12
    if year > today.year:
        return 0
    return today.month


def days_elapsed_in_year(year):
    today = date.today()
    start = date(year, 1, 1)
    end = date(year, 12, 31)
    if year > today.year:
        return 0
    if year == today.year:
        end = today
    return (end - start).days + 1


@app.route("/")
@login_required
def shelf():
    year = request.args.get("year", type=int) or date.today().year
    view = request.args.get("view", "books")
    months, rows = books_by_month(g.user["id"], year)
    max_count = max((len(v) for v in months.values()), default=0)
    reading = get_db().execute(
        "SELECT * FROM books WHERE user_id = ? AND finished_date IS NULL ORDER BY created_at DESC",
        (g.user["id"],),
    ).fetchall()
    elapsed = months_elapsed(year)
    return render_template(
        "shelf.html",
        year=year,
        view=view,
        months=months,
        total=len(rows),
        max_count=max_count,
        reading=reading,
        monthly_avg=(len(rows) / elapsed) if elapsed else 0,
    )


# ---------------------------------------------------------------- books
def get_own_book(book_id):
    book = get_db().execute(
        "SELECT * FROM books WHERE id = ? AND user_id = ?", (book_id, g.user["id"])
    ).fetchone()
    if book is None:
        abort(404)
    return book


def read_book_form():
    title = request.form.get("title", "").strip()
    author = request.form.get("author", "").strip()
    cover_url = request.form.get("cover_url", "").strip()
    if cover_url and not cover_url.startswith(("https://", "http://")):
        cover_url = ""
    status = request.form.get("status", "done")
    finished = parse_date(request.form.get("finished_date"))
    finished_date = finished.isoformat() if (status == "done" and finished) else None
    if status == "done" and finished_date is None:
        finished_date = date.today().isoformat()
    try:
        rating = max(0, min(5, int(request.form.get("rating", 0))))
    except ValueError:
        rating = 0
    review = request.form.get("review", "").strip()
    return title, author, cover_url, finished_date, rating, review


@app.route("/books/new", methods=["GET", "POST"])
@login_required
def book_new():
    if request.method == "POST":
        title, author, cover_url, finished_date, rating, review = read_book_form()
        if not title:
            flash("책 제목을 입력해 주세요.", "error")
            return render_template("book_form.html", book=None, form=request.form)
        db = get_db()
        cur = db.execute(
            """INSERT INTO books (user_id, title, author, cover_url, finished_date,
                                  rating, review, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (g.user["id"], title, author, cover_url, finished_date, rating, review,
             now_iso(), now_iso()),
        )
        db.commit()
        flash(f"『{title}』을(를) 책장에 꽂았어요!")
        return redirect(url_for("book_detail", book_id=cur.lastrowid))
    return render_template("book_form.html", book=None, form={})


@app.route("/books/<int:book_id>")
@login_required
def book_detail(book_id):
    return render_template("book_detail.html", book=get_own_book(book_id))


@app.route("/books/<int:book_id>/edit", methods=["GET", "POST"])
@login_required
def book_edit(book_id):
    book = get_own_book(book_id)
    if request.method == "POST":
        title, author, cover_url, finished_date, rating, review = read_book_form()
        if not title:
            flash("책 제목을 입력해 주세요.", "error")
            return render_template("book_form.html", book=book, form=request.form)
        db = get_db()
        db.execute(
            """UPDATE books SET title=?, author=?, cover_url=?, finished_date=?,
                   rating=?, review=?, updated_at=? WHERE id=? AND user_id=?""",
            (title, author, cover_url, finished_date, rating, review, now_iso(),
             book_id, g.user["id"]),
        )
        db.commit()
        flash("저장했어요.")
        return redirect(url_for("book_detail", book_id=book_id))
    return render_template("book_form.html", book=book, form=book)


@app.route("/books/<int:book_id>/review", methods=["POST"])
@login_required
def book_review(book_id):
    get_own_book(book_id)
    review = request.form.get("review", "").strip()
    try:
        rating = max(0, min(5, int(request.form.get("rating", 0))))
    except ValueError:
        rating = 0
    db = get_db()
    db.execute(
        "UPDATE books SET review=?, rating=?, updated_at=? WHERE id=? AND user_id=?",
        (review, rating, now_iso(), book_id, g.user["id"]),
    )
    db.commit()
    flash("독후감을 저장했어요.")
    return redirect(url_for("book_detail", book_id=book_id))


@app.route("/books/<int:book_id>/delete", methods=["POST"])
@login_required
def book_delete(book_id):
    book = get_own_book(book_id)
    db = get_db()
    db.execute("DELETE FROM books WHERE id=? AND user_id=?", (book_id, g.user["id"]))
    db.commit()
    flash(f"『{book['title']}』을(를) 책장에서 뺐어요.")
    year = book["finished_date"][:4] if book["finished_date"] else None
    return redirect(url_for("shelf", year=year))


# ---------------------------------------------------------------- calendar
@app.route("/calendar")
@login_required
def attendance_calendar():
    today = date.today()
    year = request.args.get("year", type=int) or today.year
    month = request.args.get("month", type=int) or today.month
    if not 1 <= month <= 12:
        month = today.month
    first = date(year, month, 1)
    prefix = f"{year}-{month:02d}-%"

    db = get_db()
    checks = {
        r["day"]: r
        for r in db.execute(
            "SELECT * FROM attendance WHERE user_id=? AND day LIKE ?",
            (g.user["id"], prefix),
        )
    }
    finished = {}
    for r in db.execute(
        "SELECT id, title, finished_date FROM books WHERE user_id=? AND finished_date LIKE ?",
        (g.user["id"], prefix),
    ):
        finished.setdefault(r["finished_date"], []).append(r)

    weeks = calendar.Calendar(firstweekday=6).monthdatescalendar(year, month)
    days_in_month = calendar.monthrange(year, month)[1]
    if (year, month) == (today.year, today.month):
        elapsed = today.day
    elif first > today:
        elapsed = 0
    else:
        elapsed = days_in_month

    prev_m = (first - timedelta(days=1)).replace(day=1)
    next_m = (first + timedelta(days=32)).replace(day=1)
    return render_template(
        "calendar.html",
        year=year,
        month=month,
        weeks=weeks,
        checks=checks,
        finished=finished,
        check_count=len(checks),
        elapsed=elapsed,
        rate=(len(checks) / elapsed * 100) if elapsed else 0,
        prev_m=prev_m,
        next_m=next_m,
    )


@app.route("/calendar/<day>", methods=["POST"])
@login_required
def attendance_save(day):
    d = parse_date(day)
    if d is None:
        abort(400)
    db = get_db()
    if request.form.get("action") == "delete":
        db.execute("DELETE FROM attendance WHERE user_id=? AND day=?", (g.user["id"], day))
    else:
        try:
            pages = max(0, int(request.form.get("pages") or 0))
        except ValueError:
            pages = 0
        memo = request.form.get("memo", "").strip()
        db.execute(
            """INSERT INTO attendance (user_id, day, pages, memo) VALUES (?, ?, ?, ?)
               ON CONFLICT(user_id, day) DO UPDATE SET pages=excluded.pages, memo=excluded.memo""",
            (g.user["id"], day, pages, memo),
        )
    db.commit()
    return redirect(url_for("attendance_calendar", year=d.year, month=d.month))


@app.route("/checkin", methods=["POST"])
@login_required
def checkin_today():
    db = get_db()
    db.execute(
        "INSERT OR IGNORE INTO attendance (user_id, day) VALUES (?, ?)",
        (g.user["id"], date.today().isoformat()),
    )
    db.commit()
    flash("오늘 출석 완료! 📚")
    return redirect(safe_next(request.form.get("next")))


# ---------------------------------------------------------------- stats
def streaks(days):
    """정렬된 날짜 집합으로 (현재 연속, 최장 연속) 일수를 계산."""
    if not days:
        return 0, 0
    day_set = set(days)
    longest = run = 0
    prev = None
    for d in sorted(day_set):
        run = run + 1 if prev and (d - prev).days == 1 else 1
        longest = max(longest, run)
        prev = d
    current = 0
    cursor = date.today()
    if cursor not in day_set:
        cursor -= timedelta(days=1)  # 오늘 아직 안 했어도 어제까지 이어졌으면 유지
    while cursor in day_set:
        current += 1
        cursor -= timedelta(days=1)
    return current, longest


@app.route("/stats")
@login_required
def stats():
    year = request.args.get("year", type=int) or date.today().year
    uid = g.user["id"]
    db = get_db()
    months, rows = books_by_month(uid, year)

    all_days = [
        parse_date(r["day"])
        for r in db.execute("SELECT day FROM attendance WHERE user_id=?", (uid,))
    ]
    all_days = [d for d in all_days if d]
    year_days = [d for d in all_days if d.year == year]
    current_streak, longest_streak = streaks(all_days)

    monthly = []
    today = date.today()
    for m in range(1, 13):
        dim = calendar.monthrange(year, m)[1]
        if (year, m) == (today.year, today.month):
            el = today.day
        elif date(year, m, 1) > today:
            el = 0
        else:
            el = dim
        att = sum(1 for d in year_days if d.month == m)
        monthly.append({
            "month": m,
            "books": len(months[m]),
            "days": att,
            "elapsed": el,
            "rate": (att / el * 100) if el else None,
        })
    pages_total = db.execute(
        "SELECT COALESCE(SUM(pages),0) FROM attendance WHERE user_id=? AND day LIKE ?",
        (uid, f"{year}-%"),
    ).fetchone()[0]

    elapsed_months = months_elapsed(year)
    elapsed_days = days_elapsed_in_year(year)
    rated = [r["rating"] for r in rows if r["rating"]]
    this_month = monthly[today.month - 1] if year == today.year else None
    max_books = max((x["books"] for x in monthly), default=0)

    return render_template(
        "stats.html",
        year=year,
        total=len(rows),
        monthly=monthly,
        max_books=max_books,
        monthly_avg=(len(rows) / elapsed_months) if elapsed_months else 0,
        year_rate=(len(year_days) / elapsed_days * 100) if elapsed_days else 0,
        year_days=len(year_days),
        elapsed_days=elapsed_days,
        this_month=this_month,
        current_streak=current_streak,
        longest_streak=longest_streak,
        avg_rating=(sum(rated) / len(rated)) if rated else 0,
        reviews=sum(1 for r in rows if r["review"]),
        pages_total=pages_total,
    )


if __name__ == "__main__":
    app.run(
        host=os.environ.get("HOST", "127.0.0.1"),
        port=int(os.environ.get("PORT", 5000)),
        debug=os.environ.get("FLASK_DEBUG") == "1",
    )
