import os
import sqlite3
from datetime import date, datetime, timezone
from functools import wraps
from pathlib import Path

from flask import (
    Flask,
    flash,
    g,
    jsonify,
    redirect,
    render_template,
    request,
    session,
    url_for,
)
from werkzeug.security import check_password_hash, generate_password_hash

from services.khattah import (
    get_circle,
    get_dashboard,
    get_invitations,
    get_profile,
    get_settings,
    get_transactions,
    update_profile,
    update_settings,
)

BASE_DIR = Path(__file__).resolve().parent
DATABASE_PATH = BASE_DIR / "instance" / "khattah.sqlite3"

app = Flask(__name__)
app.config["SECRET_KEY"] = os.environ.get("SESSION_SECRET", "khattah-local-development")
app.config["DATABASE"] = str(DATABASE_PATH)


def get_db():
    if "db" not in g:
        DATABASE_PATH.parent.mkdir(parents=True, exist_ok=True)
        g.db = sqlite3.connect(app.config["DATABASE"])
        g.db.row_factory = sqlite3.Row
    return g.db


@app.teardown_appcontext
def close_db(_error=None):
    database = g.pop("db", None)
    if database is not None:
        database.close()


def init_db():
    database = get_db()
    database.executescript(
        """
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            email TEXT NOT NULL UNIQUE,
            phone TEXT NOT NULL DEFAULT '',
            password_hash TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'registered',
            joined_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS invitations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            recipient TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'pending',
            sent_at TEXT NOT NULL,
            FOREIGN KEY (user_id) REFERENCES users (id)
        );
        CREATE TABLE IF NOT EXISTS transactions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            type TEXT NOT NULL,
            description TEXT NOT NULL,
            status TEXT NOT NULL,
            amount_label TEXT NOT NULL DEFAULT 'Not configured',
            occurred_at TEXT NOT NULL,
            FOREIGN KEY (user_id) REFERENCES users (id)
        );
        CREATE TABLE IF NOT EXISTS circle_members (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            name TEXT NOT NULL,
            initials TEXT NOT NULL,
            status TEXT NOT NULL,
            invited_at TEXT NOT NULL,
            FOREIGN KEY (user_id) REFERENCES users (id)
        );
        CREATE TABLE IF NOT EXISTS settings (
            user_id INTEGER PRIMARY KEY,
            email_notifications INTEGER NOT NULL DEFAULT 1,
            invitation_reminders INTEGER NOT NULL DEFAULT 1,
            preferred_language TEXT NOT NULL DEFAULT 'en',
            FOREIGN KEY (user_id) REFERENCES users (id)
        );
        """
    )
    demo = database.execute(
        "SELECT id FROM users WHERE email = ?", ("demo@khattah.app",)
    ).fetchone()
    if demo is None:
        cursor = database.execute(
            """
            INSERT INTO users (name, email, phone, password_hash, status, joined_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                "Amina Yusuf",
                "demo@khattah.app",
                "+1 306 555 0184",
                generate_password_hash("Demo1234!"),
                "activated",
                "2026-09-08",
            ),
        )
        user_id = cursor.lastrowid
        database.executemany(
            """
            INSERT INTO invitations (user_id, recipient, status, sent_at)
            VALUES (?, ?, ?, ?)
            """,
            [
                (user_id, "Nadia Ali", "joined", "2026-09-10"),
                (user_id, "Samira Khan", "opened", "2026-09-12"),
                (user_id, "Fatima Noor", "pending", "2026-09-15"),
            ],
        )
        database.executemany(
            """
            INSERT INTO transactions
                (user_id, type, description, status, amount_label, occurred_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            [
                (
                    user_id,
                    "Account",
                    "Account created",
                    "Registered",
                    "No amount",
                    "2026-09-08T09:30:00+00:00",
                ),
                (
                    user_id,
                    "Invitation",
                    "Nadia Ali joined from your invitation",
                    "Completed",
                    "No amount",
                    "2026-09-10T15:10:00+00:00",
                ),
            ],
        )
        database.executemany(
            """
            INSERT INTO circle_members (user_id, name, initials, status, invited_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            [
                (user_id, "Nadia Ali", "NA", "paid", "2026-09-10"),
                (user_id, "Samira Khan", "SK", "registered", "2026-09-12"),
                (user_id, "Fatima Noor", "FN", "invited", "2026-09-15"),
            ],
        )
        database.execute(
            """
            INSERT INTO settings
                (user_id, email_notifications, invitation_reminders, preferred_language)
            VALUES (?, ?, ?, ?)
            """,
            (user_id, 1, 1, "en"),
        )
        database.commit()


def current_user():
    user_id = session.get("user_id")
    if not user_id:
        return None
    return get_db().execute(
        "SELECT * FROM users WHERE id = ?", (user_id,)
    ).fetchone()


def login_required(view):
    @wraps(view)
    def wrapped_view(**kwargs):
        if current_user() is None:
            flash("Sign in to view your Khattah account.", "info")
            return redirect(url_for("login", next=request.path))
        return view(**kwargs)

    return wrapped_view


@app.context_processor
def inject_navigation():
    return {"current_user": current_user(), "today": date.today()}


@app.before_request
def prepare_database():
    init_db()


@app.get("/")
def welcome():
    return render_template("welcome.html")


@app.route("/register", methods=("GET", "POST"))
def register():
    if request.method == "POST":
        name = request.form.get("name", "").strip()
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")
        if not name or not email or len(password) < 8:
            flash("Enter your name, a valid email, and a password with at least 8 characters.", "error")
            return render_template("auth.html", mode="register")
        try:
            cursor = get_db().execute(
                """
                INSERT INTO users (name, email, password_hash, status, joined_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (name, email, generate_password_hash(password), "registered", date.today().isoformat()),
            )
            user_id = cursor.lastrowid
            get_db().execute(
                "INSERT INTO settings (user_id) VALUES (?)", (user_id,)
            )
            get_db().commit()
        except sqlite3.IntegrityError:
            flash("That email is already registered. Try signing in instead.", "error")
            return render_template("auth.html", mode="register")
        session.clear()
        session["user_id"] = user_id
        flash("Your Khattah account is ready.", "success")
        return redirect(url_for("dashboard"))
    return render_template("auth.html", mode="register")


@app.route("/login", methods=("GET", "POST"))
def login():
    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")
        user = get_db().execute(
            "SELECT * FROM users WHERE email = ?", (email,)
        ).fetchone()
        if user is None or not check_password_hash(user["password_hash"], password):
            flash("Those sign-in details do not match our records.", "error")
            return render_template("auth.html", mode="login")
        session.clear()
        session["user_id"] = user["id"]
        return redirect(request.args.get("next") or url_for("dashboard"))
    return render_template("auth.html", mode="login")


@app.get("/demo")
def demo_login():
    demo = get_db().execute(
        "SELECT id FROM users WHERE email = ?", ("demo@khattah.app",)
    ).fetchone()
    session.clear()
    session["user_id"] = demo["id"]
    return redirect(url_for("dashboard"))


@app.get("/logout")
def logout():
    session.clear()
    flash("You have been signed out.", "info")
    return redirect(url_for("welcome"))


@app.get("/dashboard")
@login_required
def dashboard():
    return render_template("dashboard.html", page="dashboard", data=get_dashboard(get_db(), session["user_id"]))


@app.get("/circle")
@login_required
def circle():
    return render_template("circle.html", page="circle", data=get_circle(get_db(), session["user_id"]))


@app.route("/invitations", methods=("GET", "POST"))
@login_required
def invitations():
    if request.method == "POST":
        recipient = request.form.get("recipient", "").strip()
        if not recipient:
            flash("Add an email address or phone number to send an invitation.", "error")
        else:
            get_db().execute(
                """
                INSERT INTO invitations (user_id, recipient, status, sent_at)
                VALUES (?, ?, ?, ?)
                """,
                (session["user_id"], recipient, "pending", datetime.now(timezone.utc).date().isoformat()),
            )
            get_db().commit()
            flash("Invitation added to your list.", "success")
        return redirect(url_for("invitations"))
    return render_template("invitations.html", page="invitations", data=get_invitations(get_db(), session["user_id"]))


@app.get("/transactions")
@login_required
def transactions():
    return render_template("transactions.html", page="transactions", data=get_transactions(get_db(), session["user_id"]))


@app.route("/profile", methods=("GET", "POST"))
@login_required
def profile():
    if request.method == "POST":
        update_profile(
            get_db(),
            session["user_id"],
            request.form.get("name", "").strip(),
            request.form.get("phone", "").strip(),
        )
        get_db().commit()
        flash("Profile updated.", "success")
        return redirect(url_for("profile"))
    return render_template("profile.html", page="profile", data=get_profile(get_db(), session["user_id"]))


@app.route("/settings", methods=("GET", "POST"))
@login_required
def settings():
    if request.method == "POST":
        update_settings(
            get_db(),
            session["user_id"],
            bool(request.form.get("email_notifications")),
            bool(request.form.get("invitation_reminders")),
            request.form.get("preferred_language", "en"),
        )
        get_db().commit()
        flash("Settings saved.", "success")
        return redirect(url_for("settings"))
    return render_template("settings.html", page="settings", data=get_settings(get_db(), session["user_id"]))


@app.errorhandler(404)
def not_found(_error):
    return render_template("404.html"), 404


@app.get("/api/v1/dashboard")
@login_required
def api_dashboard():
    return jsonify(get_dashboard(get_db(), session["user_id"]))


@app.get("/api/v1/circle")
@login_required
def api_circle():
    return jsonify(get_circle(get_db(), session["user_id"]))


@app.route("/api/v1/invitations", methods=("GET", "POST"))
@login_required
def api_invitations():
    if request.method == "POST":
        payload = request.get_json(silent=True) or {}
        recipient = str(payload.get("recipient", "")).strip()
        if not recipient:
            return jsonify({"error": "recipient is required"}), 400
        get_db().execute(
            """
            INSERT INTO invitations (user_id, recipient, status, sent_at)
            VALUES (?, ?, ?, ?)
            """,
            (session["user_id"], recipient, "pending", date.today().isoformat()),
        )
        get_db().commit()
    return jsonify(get_invitations(get_db(), session["user_id"]))


@app.get("/api/v1/transactions")
@login_required
def api_transactions():
    return jsonify(get_transactions(get_db(), session["user_id"]))


@app.route("/api/v1/profile", methods=("GET", "PATCH"))
@login_required
def api_profile():
    if request.method == "PATCH":
        payload = request.get_json(silent=True) or {}
        update_profile(
            get_db(),
            session["user_id"],
            str(payload.get("name", "")).strip(),
            str(payload.get("phone", "")).strip(),
        )
        get_db().commit()
    return jsonify(get_profile(get_db(), session["user_id"]))


@app.route("/api/v1/settings", methods=("GET", "PATCH"))
@login_required
def api_settings():
    if request.method == "PATCH":
        payload = request.get_json(silent=True) or {}
        update_settings(
            get_db(),
            session["user_id"],
            bool(payload.get("email_notifications", True)),
            bool(payload.get("invitation_reminders", True)),
            str(payload.get("preferred_language", "en")),
        )
        get_db().commit()
    return jsonify(get_settings(get_db(), session["user_id"]))


if __name__ == "__main__":
    with app.app_context():
        init_db()
    port = int(os.environ.get("PORT", "5000"))
    app.run(host="0.0.0.0", port=port, debug=False)