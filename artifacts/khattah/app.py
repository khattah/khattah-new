import os
import hashlib
import hmac
import secrets
import sqlite3
from datetime import date, datetime, timedelta, timezone
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
from werkzeug.middleware.proxy_fix import ProxyFix

from services.khattah import (
    activate_invitation,
    create_invitation,
    ensure_active_circle,  # Legacy compatibility import.
    ensure_active_package,
    get_admin_overview,
    get_circle,
    get_circle_history,
    get_package,
    get_package_history,
    get_dashboard,
    get_invitations,
    get_profile,
    get_rewards,
    get_settings,
    get_transactions,
    start_new_circle,
    start_new_package,
    update_profile,
    update_settings,
    utc_now,
)
from services.phone_verification import (
    DuplicatePhoneError,
    PhoneVerificationError,
    VerificationRateLimitError,
    mask_phone,
    normalize_mobile_number,
    request_verification,
    verify_code,
)
from services.i18n import normalize_language, translate
from services.invitation_messages import (
    available_messages, create_message, get_message, list_messages,
    make_invite_token, read_invite_token, render_message, set_message_state,
    update_message, get_message_audit, CHANNELS,
)
from services.appearance import (
    DEFAULT_PALETTES, TEMPLATE_KEYS, COLOR_FIELDS, ICON_ALLOWLIST,
    activate as activate_appearance, audit_rows as appearance_audit_rows,
    get_colors as get_appearance_colors, get_package_display,
    get_settings as get_appearance_settings, list_colors,
    list_package_display, reset_colors, save_colors, save_package,
)

BASE_DIR = Path(__file__).resolve().parent
DATABASE_PATH = BASE_DIR / "instance" / "khattah.sqlite3"

app = Flask(__name__)
app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1)
app.config.update(
    SECRET_KEY=os.environ.get("SESSION_SECRET", "khattah-local-development"),
    DATABASE=str(DATABASE_PATH),
    SEED_DEMO_DATA=os.environ.get(
        "KHATTAH_DEMO_MODE",
        "0" if os.environ.get("REPLIT_DEPLOYMENT") else "1",
    )
    == "1",
    DEMO_FIXED_OTP="123456",
    PHONE_API_REQUESTS_PER_HOUR=10,
)

LANGUAGE_COOKIE = "khattah_language"

COUNTRY_CODES = [
    ("Canada / United States", "+1"),
    ("United Kingdom", "+44"),
    ("Kenya", "+254"),
    ("Somalia", "+252"),
    ("Nigeria", "+234"),
    ("Ghana", "+233"),
    ("Ethiopia", "+251"),
    ("Uganda", "+256"),
    ("Tanzania", "+255"),
    ("South Africa", "+27"),
    ("United Arab Emirates", "+971"),
    ("Saudi Arabia", "+966"),
    ("Qatar", "+974"),
    ("Kuwait", "+965"),
    ("Australia", "+61"),
]


def get_db():
    if "db" not in g:
        Path(app.config["DATABASE"]).parent.mkdir(parents=True, exist_ok=True)
        g.db = sqlite3.connect(app.config["DATABASE"])
        g.db.row_factory = sqlite3.Row
        g.db.execute("PRAGMA foreign_keys = ON")
    return g.db


@app.teardown_appcontext
def close_db(_error=None):
    database = g.pop("db", None)
    if database is not None:
        database.close()


def _column_exists(database, table, column):
    return any(row["name"] == column for row in database.execute(f"PRAGMA table_info({table})"))


def migrate_db():
    database = get_db()
    # Persistence compatibility: historical circles/circle_participants and
    # circle_id columns remain the single source of truth for package history.
    # They are intentionally not renamed or duplicated during terminology work.
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
    if not _column_exists(database, "users", "is_admin"):
        database.execute("ALTER TABLE users ADD COLUMN is_admin INTEGER NOT NULL DEFAULT 0")
    if not _column_exists(database, "users", "country_calling_code"):
        database.execute("ALTER TABLE users ADD COLUMN country_calling_code TEXT NOT NULL DEFAULT ''")
    if not _column_exists(database, "users", "normalized_phone"):
        database.execute("ALTER TABLE users ADD COLUMN normalized_phone TEXT")
    if not _column_exists(database, "users", "phone_verified"):
        database.execute("ALTER TABLE users ADD COLUMN phone_verified INTEGER NOT NULL DEFAULT 0")
    if not _column_exists(database, "users", "phone_verified_at"):
        database.execute("ALTER TABLE users ADD COLUMN phone_verified_at TEXT")
    if not _column_exists(database, "invitations", "invitation_message_id"):
        database.execute("ALTER TABLE invitations ADD COLUMN invitation_message_id INTEGER")

    database.executescript(
        """
        CREATE UNIQUE INDEX IF NOT EXISTS unique_verified_mobile
            ON users(normalized_phone)
            WHERE normalized_phone IS NOT NULL AND normalized_phone != '';
        CREATE TABLE IF NOT EXISTS pending_registrations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            email TEXT NOT NULL,
            password_hash TEXT NOT NULL,
            country_calling_code TEXT NOT NULL,
            mobile_number TEXT NOT NULL,
            normalized_phone TEXT NOT NULL,
            created_at TEXT NOT NULL,
            expires_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS phone_verification_challenges (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            challenge_token TEXT NOT NULL UNIQUE,
            pending_registration_id INTEGER,
            country_calling_code TEXT NOT NULL,
            normalized_phone TEXT NOT NULL,
            code_hash TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'pending',
            attempts_remaining INTEGER NOT NULL DEFAULT 5,
            send_count INTEGER NOT NULL DEFAULT 1,
            send_window_started_at TEXT NOT NULL,
            expires_at TEXT NOT NULL,
            resend_available_at TEXT NOT NULL,
            created_at TEXT NOT NULL,
            verified_at TEXT,
            FOREIGN KEY (pending_registration_id)
                REFERENCES pending_registrations (id) ON DELETE SET NULL
        );
        CREATE INDEX IF NOT EXISTS phone_challenge_lookup
            ON phone_verification_challenges(normalized_phone, status);
        CREATE TABLE IF NOT EXISTS phone_verification_request_limits (
            limiter_key TEXT PRIMARY KEY,
            request_count INTEGER NOT NULL,
            window_started_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS schema_migrations (
            version INTEGER PRIMARY KEY,
            applied_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS circles (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            sequence_number INTEGER NOT NULL,
            status TEXT NOT NULL DEFAULT 'active',
            required_participants INTEGER NOT NULL DEFAULT 5,
            created_at TEXT NOT NULL,
            completed_at TEXT,
            FOREIGN KEY (user_id) REFERENCES users (id),
            UNIQUE (user_id, sequence_number)
        );
        CREATE UNIQUE INDEX IF NOT EXISTS one_active_circle_per_user
            ON circles(user_id) WHERE status = 'active';
        CREATE TABLE IF NOT EXISTS activations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            invitation_id INTEGER NOT NULL UNIQUE,
            user_id INTEGER NOT NULL,
            marked_by_user_id INTEGER NOT NULL,
            status TEXT NOT NULL DEFAULT 'paid',
            activated_at TEXT NOT NULL,
            FOREIGN KEY (invitation_id) REFERENCES invitations (id),
            FOREIGN KEY (user_id) REFERENCES users (id),
            FOREIGN KEY (marked_by_user_id) REFERENCES users (id)
        );
        CREATE TABLE IF NOT EXISTS circle_participants (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            circle_id INTEGER NOT NULL,
            invitation_id INTEGER NOT NULL UNIQUE,
            position_number INTEGER NOT NULL,
            status TEXT NOT NULL DEFAULT 'qualified',
            qualified_at TEXT NOT NULL,
            FOREIGN KEY (circle_id) REFERENCES circles (id),
            FOREIGN KEY (invitation_id) REFERENCES invitations (id),
            UNIQUE (circle_id, position_number)
        );
        CREATE TABLE IF NOT EXISTS rewards (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            circle_id INTEGER NOT NULL UNIQUE,
            status TEXT NOT NULL DEFAULT 'available',
            eligible_at TEXT NOT NULL,
            redeemed_at TEXT,
            FOREIGN KEY (user_id) REFERENCES users (id),
            FOREIGN KEY (circle_id) REFERENCES circles (id)
        );
        CREATE TABLE IF NOT EXISTS audit_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            event_type TEXT NOT NULL,
            description TEXT NOT NULL,
            entity_type TEXT,
            entity_id INTEGER,
            occurred_at TEXT NOT NULL,
            FOREIGN KEY (user_id) REFERENCES users (id)
        );
        CREATE INDEX IF NOT EXISTS audit_events_user_time
            ON audit_events(user_id, occurred_at DESC);
        """
    )
    database.execute(
        "INSERT OR IGNORE INTO schema_migrations (version, applied_at) VALUES (2, ?)",
        (utc_now(),),
    )
    database.execute(
        "INSERT OR IGNORE INTO schema_migrations (version, applied_at) VALUES (3, ?)",
        (utc_now(),),
    )
    # Version 201 is deliberately narrow and idempotent: it corrects only the
    # known demo scenario label, never touching its ID or related records.
    marker = database.execute(
        "SELECT 1 FROM schema_migrations WHERE version = 201"
    ).fetchone()
    if marker is None:
        database.execute(
            """
            UPDATE users
            SET name = 'Multiple Packages'
            WHERE email = 'multiple@khattah.app'
              AND name = 'Multiple Circles'
            """
        )
        database.execute(
            "INSERT INTO schema_migrations (version, applied_at) VALUES (201, ?)",
            (utc_now(),),
        )
    database.executescript(
        """
        CREATE TABLE IF NOT EXISTS invitation_messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            campaign_name TEXT NOT NULL,
            channel TEXT NOT NULL,
            language TEXT NOT NULL,
            subject TEXT NOT NULL DEFAULT '',
            body TEXT NOT NULL,
            is_approved INTEGER NOT NULL DEFAULT 0,
            is_active INTEGER NOT NULL DEFAULT 0,
            is_archived INTEGER NOT NULL DEFAULT 0,
            created_by_user_id INTEGER NOT NULL,
            updated_by_user_id INTEGER NOT NULL,
            approved_by_user_id INTEGER,
            activated_by_user_id INTEGER,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            approved_at TEXT,
            activated_at TEXT,
            archived_at TEXT,
            FOREIGN KEY (created_by_user_id) REFERENCES users(id),
            FOREIGN KEY (updated_by_user_id) REFERENCES users(id)
        );
        CREATE TABLE IF NOT EXISTS invitation_message_audit (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            message_id INTEGER NOT NULL,
            actor_user_id INTEGER NOT NULL,
            action TEXT NOT NULL,
            occurred_at TEXT NOT NULL,
            details TEXT NOT NULL DEFAULT '',
            FOREIGN KEY (message_id) REFERENCES invitation_messages(id),
            FOREIGN KEY (actor_user_id) REFERENCES users(id)
        );
        CREATE INDEX IF NOT EXISTS invitation_message_state
            ON invitation_messages(channel, language, is_approved, is_active, is_archived);
        """
    )
    database.execute(
        "INSERT OR IGNORE INTO schema_migrations (version, applied_at) VALUES (202, ?)",
        (utc_now(),),
    )
    database.executescript(
        """
        CREATE TABLE IF NOT EXISTS appearance_settings (
            id INTEGER PRIMARY KEY CHECK (id = 1),
            active_frontend_template TEXT NOT NULL DEFAULT 'classic'
                CHECK (active_frontend_template IN ('classic','modern','minimal','premium','mobile')),
            active_admin_template TEXT NOT NULL DEFAULT 'classic'
                CHECK (active_admin_template IN ('classic','modern','minimal','premium','mobile')),
            updated_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS template_color_settings (
            template_key TEXT PRIMARY KEY CHECK (template_key IN ('classic','modern','minimal','premium','mobile')),
            primary_color TEXT NOT NULL, secondary_color TEXT NOT NULL,
            background_color TEXT NOT NULL, header_color TEXT NOT NULL,
            navigation_color TEXT NOT NULL, button_color TEXT NOT NULL,
            card_color TEXT NOT NULL, text_color TEXT NOT NULL,
            link_color TEXT NOT NULL, border_color TEXT NOT NULL,
            status_invited TEXT NOT NULL, status_paid TEXT NOT NULL,
            status_reward TEXT NOT NULL, status_completed TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS package_display_settings (
            sequence_number INTEGER PRIMARY KEY CHECK (sequence_number > 0),
            name_en TEXT NOT NULL DEFAULT '', name_ar TEXT NOT NULL DEFAULT '',
            description_en TEXT NOT NULL DEFAULT '', description_ar TEXT NOT NULL DEFAULT '',
            icon TEXT NOT NULL DEFAULT 'package',
            display_order INTEGER NOT NULL DEFAULT 0,
            is_visible INTEGER NOT NULL DEFAULT 1,
            is_active INTEGER NOT NULL DEFAULT 1,
            updated_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS appearance_audit (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            category TEXT NOT NULL, setting_key TEXT NOT NULL,
            previous_value TEXT, new_value TEXT,
            actor_user_id INTEGER NOT NULL, occurred_at TEXT NOT NULL,
            FOREIGN KEY (actor_user_id) REFERENCES users(id)
        );
        """
    )
    database.execute(
        "INSERT OR IGNORE INTO appearance_settings (id, updated_at) VALUES (1, ?)",
        (utc_now(),),
    )
    for key, palette in DEFAULT_PALETTES.items():
        database.execute("""INSERT OR IGNORE INTO template_color_settings
            (template_key, primary_color, secondary_color, background_color, header_color,
             navigation_color, button_color, card_color, text_color, link_color, border_color,
             status_invited, status_paid, status_reward, status_completed, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (key, palette["primary"], palette["secondary"], palette["background"],
             palette["header"], palette["navigation"], palette["button"], palette["card"],
             palette["text"], palette["link"], palette["border"],
             palette["status_invited"], palette["status_paid"], palette["status_reward"],
             palette["status_completed"], utc_now()))
    package_defaults = [
        (1, "Starter", "الأساسية"), (2, "Standard", "القياسية"),
        (3, "Advanced", "المتقدمة"), (4, "Premium", "المميزة"), (5, "Elite", "النخبة"),
    ]
    for sequence, name_en, name_ar in package_defaults:
        database.execute("""INSERT OR IGNORE INTO package_display_settings
            (sequence_number,name_en,name_ar,display_order,updated_at)
            VALUES (?, ?, ?, ?, ?)""",
            (sequence, name_en, name_ar, sequence, utc_now()))
    database.execute(
        "INSERT OR IGNORE INTO schema_migrations (version, applied_at) VALUES (204, ?)",
        (utc_now(),),
    )
    database.commit()


def _create_user(
    database,
    name,
    email,
    status="registered",
    is_admin=False,
    password="Demo1234!",
):
    row = database.execute("SELECT id FROM users WHERE email = ?", (email,)).fetchone()
    if row:
        return row["id"]
    cursor = database.execute(
        """
        INSERT INTO users
            (name, email, phone, password_hash, status, joined_at, is_admin)
        VALUES (?, ?, '', ?, ?, ?, ?)
        """,
        (
            name,
            email,
            generate_password_hash(password),
            status,
            date.today().isoformat(),
            int(is_admin),
        ),
    )
    user_id = cursor.lastrowid
    database.execute("INSERT INTO settings (user_id) VALUES (?)", (user_id,))
    return user_id


def _seed_qualified_participants(database, user_id, administrator_id, count):
    existing = database.execute(
        "SELECT COUNT(*) AS count FROM activations WHERE user_id = ?", (user_id,)
    ).fetchone()["count"]
    for index in range(existing + 1, count + 1):
        invitation = create_invitation(database, user_id, f"Participant {index}")
        activate_invitation(database, invitation["id"], administrator_id)


def seed_demo_data():
    if not app.config["SEED_DEMO_DATA"]:
        return
    database = get_db()
    admin_id = _create_user(
        database,
        "DEMO / DEVELOPMENT Administrator",
        "admin@khattah.test",
        "activated",
        True,
        "Admin123!",
    )
    if database.execute("SELECT 1 FROM schema_migrations WHERE version=203").fetchone() is None:
        for channel in CHANNELS:
            for language in ("en", "ar"):
                row = create_message(database, admin_id, {
                    "campaign_name": "DEMO / DEVELOPMENT invitation messages",
                    "channel": channel, "language": language,
                    "subject": "You are invited to KHATTAH" if language == "en" else "أنت مدعو إلى خطّة",
                    "body": "Join {inviter_name} on KHATTAH: {invite_link}" if language == "en"
                            else "انضم إلى {inviter_name} في خطّة: {invite_link}",
                })
                set_message_state(database, row["id"], admin_id, "approve")
                set_message_state(database, row["id"], admin_id, "activate")
        database.execute("INSERT INTO schema_migrations (version, applied_at) VALUES (203, ?)", (utc_now(),))
    demo_id = _create_user(
        database,
        "DEMO / DEVELOPMENT Member",
        "demo@khattah.test",
        "activated",
        False,
        "Demo123!",
    )
    ensure_active_package(database, demo_id)
    _seed_qualified_participants(database, demo_id, admin_id, 4)

    marker = database.execute(
        "SELECT version FROM schema_migrations WHERE version = 200"
    ).fetchone()
    if marker is None:
        scenarios = [
            ("Scenario 0 of 5", "scenario0@khattah.app", 0),
            ("Scenario 1 of 5", "scenario1@khattah.app", 1),
            ("Scenario 4 of 5", "scenario4@khattah.app", 4),
            ("Scenario 5 of 5", "scenario5@khattah.app", 5),
            ("Multiple Packages", "multiple@khattah.app", 10),
        ]
        for name, email, qualified_count in scenarios:
            user_id = _create_user(database, name, email, "activated", False)
            ensure_active_package(database, user_id)
            _seed_qualified_participants(database, user_id, admin_id, qualified_count)
            if email == "multiple@khattah.app":
                start_new_package(database, user_id)
        database.execute(
            "INSERT INTO schema_migrations (version, applied_at) VALUES (200, ?)",
            (utc_now(),),
        )
    database.commit()


def init_db():
    migrate_db()
    seed_demo_data()


def request_phone_verification(database, country_code, mobile_number, **kwargs):
    fixed_code = (
        app.config["DEMO_FIXED_OTP"] if app.config["SEED_DEMO_DATA"] else None
    )
    return request_verification(
        database,
        country_code,
        mobile_number,
        fixed_code=fixed_code,
        **kwargs,
    )


def record_phone_api_request():
    client_address = request.remote_addr or "unknown"
    limiter_key = hashlib.sha256(client_address.encode("utf-8")).hexdigest()
    now = datetime.now(timezone.utc)
    row = get_db().execute(
        """
        SELECT request_count, window_started_at
        FROM phone_verification_request_limits
        WHERE limiter_key = ?
        """,
        (limiter_key,),
    ).fetchone()
    limit = int(app.config["PHONE_API_REQUESTS_PER_HOUR"])
    if row is None:
        get_db().execute(
            """
            INSERT INTO phone_verification_request_limits
                (limiter_key, request_count, window_started_at)
            VALUES (?, 1, ?)
            """,
            (limiter_key, now.isoformat()),
        )
    elif now - datetime.fromisoformat(row["window_started_at"]) >= timedelta(hours=1):
        get_db().execute(
            """
            UPDATE phone_verification_request_limits
            SET request_count = 1, window_started_at = ?
            WHERE limiter_key = ?
            """,
            (now.isoformat(), limiter_key),
        )
    elif row["request_count"] >= limit:
        raise VerificationRateLimitError(
            "Too many verification requests from this client. Try again later."
        )
    else:
        get_db().execute(
            """
            UPDATE phone_verification_request_limits
            SET request_count = request_count + 1
            WHERE limiter_key = ?
            """,
            (limiter_key,),
        )
    get_db().commit()


def current_user():
    user_id = session.get("user_id")
    if not user_id:
        return None
    return get_db().execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()


def api_error(message, status):
    return jsonify({"error": translate(message, getattr(g, "language", "en"))}), status


def login_required(view):
    @wraps(view)
    def wrapped_view(**kwargs):
        if current_user() is None:
            flash("Sign in to view your Khattah account.", "info")
            return redirect(url_for("login", next=request.path))
        return view(**kwargs)

    return wrapped_view


def api_login_required(view):
    @wraps(view)
    def wrapped_view(**kwargs):
        if current_user() is None:
            return api_error("authentication required", 401)
        return view(**kwargs)

    return wrapped_view


def admin_required(view):
    @wraps(view)
    def wrapped_view(**kwargs):
        user = current_user()
        if user is None:
            return redirect(url_for("login", next=request.path))
        if not user["is_admin"]:
            flash("Administrator access is required.", "error")
            return redirect(url_for("dashboard"))
        return view(**kwargs)

    return wrapped_view


def api_admin_required(view):
    @wraps(view)
    def wrapped_view(**kwargs):
        user = current_user()
        if user is None:
            return api_error("authentication required", 401)
        if not user["is_admin"]:
            return api_error("administrator access required", 403)
        return view(**kwargs)

    return wrapped_view


@app.context_processor
def inject_navigation():
    language = getattr(g, "language", "en")
    appearance = getattr(g, "appearance", {"colors": {}})
    return {
        "current_user": current_user(),
        "today": date.today(),
        "csrf_token": session.get("csrf_token", ""),
        "current_language": language,
        "text_direction": "rtl" if language == "ar" else "ltr",
        "languages": (("en", "English"), ("ar", "العربية")),
        "t": lambda value, **variables: translate(value, language, **variables),
        "appearance": appearance,
        "package_display": lambda sequence: get_package_display(
            get_db(), sequence, language
        ),
    }


@app.before_request
def prepare_database():
    init_db()
    if "csrf_token" not in session:
        session["csrf_token"] = secrets.token_urlsafe(32)
    user = current_user()
    if user is not None:
        preference = get_settings(get_db(), user["id"])["preferred_language"]
        g.language = normalize_language(preference)
        session["language"] = g.language
    else:
        g.language = normalize_language(
            session.get("language") or request.cookies.get(LANGUAGE_COOKIE, "en")
        )
    appearance = get_appearance_settings(get_db())
    admin_user = user is not None and bool(user["is_admin"])
    admin_surface = request.path == "/admin" or request.path.startswith("/admin/")
    admin_surface = admin_surface or request.path == "/api/v1/admin/overview"
    admin_surface = admin_surface or request.path.startswith("/api/v1/admin/appearance")
    scope = "admin" if admin_surface else "frontend"
    preview = request.args.get("preview", "")
    preview_scope = request.args.get("preview_scope", request.args.get("scope", ""))
    # Preview is deliberately restricted to administrators.  A frontend
    # preview may be requested while viewing a normal page; admin surfaces
    # always preview the admin scope unless explicitly requesting frontend.
    if admin_user and preview in TEMPLATE_KEYS and (
        (preview_scope in ("", scope)) or preview_scope == scope
    ):
        selected_key = preview
    else:
        selected_key = (
            appearance["active_admin_template"]
            if scope == "admin" else appearance["active_frontend_template"]
        )
    g.appearance = {
        **appearance,
        "template_key": selected_key,
        "theme_scope": scope,
        "colors": get_appearance_colors(get_db(), selected_key),
    }
    public_phone_api = request.path in {
        "/api/v1/phone-verification/request",
        "/api/v1/phone-verification/verify",
    }
    if request.method in {"POST", "PUT", "PATCH", "DELETE"} and not public_phone_api:
        supplied = request.form.get("csrf_token") or request.headers.get("X-CSRF-Token", "")
        expected = session.get("csrf_token", "")
        if not supplied or not hmac.compare_digest(supplied, expected):
            if request.path.startswith("/api/"):
                return api_error("invalid csrf token", 400)
            return "Invalid or missing request token.", 400


@app.after_request
def persist_language_cookie(response):
    response.set_cookie(
        LANGUAGE_COOKIE,
        getattr(g, "language", "en"),
        max_age=60 * 60 * 24 * 365,
        samesite="Lax",
    )
    return response


@app.get("/language/<language>")
def set_language(language):
    language = normalize_language(language)
    session["language"] = language
    user = current_user()
    if user is not None:
        settings = get_settings(get_db(), user["id"])
        update_settings(
            get_db(),
            user["id"],
            settings["email_notifications"],
            settings["invitation_reminders"],
            language,
        )
        get_db().commit()
    target = request.args.get("next", "")
    if not target.startswith("/") or target.startswith("//"):
        target = request.referrer or url_for("welcome")
    return redirect(target)


@app.get("/")
def welcome():
    return render_template("welcome.html")


@app.route("/register", methods=("GET", "POST"))
def register():
    if request.method == "POST":
        name = request.form.get("name", "").strip()
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")
        country_code = request.form.get("country_code", "")
        mobile_number = request.form.get("mobile_number", "").strip()
        form_values = {
            "name": name,
            "email": email,
            "country_code": country_code,
            "mobile_number": mobile_number,
        }
        if not name or "@" not in email or len(password) < 8:
            flash("Enter your name, a valid email, and a password with at least 8 characters.", "error")
            return render_template(
                "auth.html",
                mode="register",
                country_codes=COUNTRY_CODES,
                form_values=form_values,
            )
        try:
            calling_code, normalized_phone = normalize_mobile_number(
                country_code, mobile_number
            )
            existing_email = get_db().execute(
                "SELECT id FROM users WHERE email = ?", (email,)
            ).fetchone()
            if existing_email is not None:
                raise sqlite3.IntegrityError("email already registered")

            pending_id = session.get("pending_registration_id")
            pending = (
                get_db().execute(
                    "SELECT id FROM pending_registrations WHERE id = ?",
                    (pending_id,),
                ).fetchone()
                if pending_id
                else None
            )
            expires_at = (
                date.today().isoformat() + "T23:59:59+00:00"
            )
            if pending is None:
                cursor = get_db().execute(
                    """
                    INSERT INTO pending_registrations (
                        name, email, password_hash, country_calling_code,
                        mobile_number, normalized_phone, created_at, expires_at
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        name,
                        email,
                        generate_password_hash(password),
                        calling_code,
                        mobile_number,
                        normalized_phone,
                        utc_now(),
                        expires_at,
                    ),
                )
                pending_id = cursor.lastrowid
            else:
                get_db().execute(
                    """
                    UPDATE pending_registrations
                    SET name = ?, email = ?, password_hash = ?,
                        country_calling_code = ?, mobile_number = ?,
                        normalized_phone = ?, created_at = ?, expires_at = ?
                    WHERE id = ?
                    """,
                    (
                        name,
                        email,
                        generate_password_hash(password),
                        calling_code,
                        mobile_number,
                        normalized_phone,
                        utc_now(),
                        expires_at,
                        pending_id,
                    ),
                )
            challenge = request_phone_verification(
                get_db(),
                calling_code,
                mobile_number,
                pending_registration_id=pending_id,
            )
            get_db().commit()
        except VerificationRateLimitError as error:
            get_db().rollback()
            flash(str(error), "error")
            return render_template(
                "auth.html",
                mode="register",
                country_codes=COUNTRY_CODES,
                form_values=form_values,
            )
        except (PhoneVerificationError, sqlite3.IntegrityError) as error:
            get_db().rollback()
            message = (
                "That email is already registered. Try signing in instead."
                if isinstance(error, sqlite3.IntegrityError)
                else str(error)
            )
            flash(message, "error")
            return render_template(
                "auth.html",
                mode="register",
                country_codes=COUNTRY_CODES,
                form_values=form_values,
            )

        session["pending_registration_id"] = pending_id
        session["phone_challenge_token"] = challenge["challenge_token"]
        flash(
            "Verification code sent through the development mock SMS service.",
            "success",
        )
        return render_template(
            "auth.html",
            mode="register",
            country_codes=COUNTRY_CODES,
            verification_sent=True,
            masked_phone=challenge["masked_phone"],
            form_values=form_values,
        )
    return render_template(
        "auth.html",
        mode="register",
        country_codes=COUNTRY_CODES,
        form_values={},
    )


@app.post("/register/verify")
def register_verify():
    pending_id = session.get("pending_registration_id")
    challenge_token = session.get("phone_challenge_token")
    code = request.form.get("verification_code", "")
    pending = get_db().execute(
        "SELECT * FROM pending_registrations WHERE id = ?", (pending_id,)
    ).fetchone()
    if pending is None or not challenge_token:
        flash("Start registration before verifying a mobile number.", "error")
        return redirect(url_for("register"))
    try:
        verified = verify_code(get_db(), challenge_token, code)
        if verified["pending_registration_id"] != pending_id:
            raise PhoneVerificationError("Verification request does not match this registration.")
        cursor = get_db().execute(
            """
            INSERT INTO users (
                name, email, phone, password_hash, status, joined_at, is_admin,
                country_calling_code, normalized_phone,
                phone_verified, phone_verified_at
            )
            VALUES (?, ?, ?, ?, 'registered', ?, 0, ?, ?, 1, ?)
            """,
            (
                pending["name"],
                pending["email"],
                verified["normalized_phone"],
                pending["password_hash"],
                date.today().isoformat(),
                verified["country_calling_code"],
                verified["normalized_phone"],
                verified["verified_at"],
            ),
        )
        user_id = cursor.lastrowid
        get_db().execute("INSERT INTO settings (user_id) VALUES (?)", (user_id,))
        ensure_active_package(get_db(), user_id)
        get_db().execute(
            "DELETE FROM pending_registrations WHERE id = ?", (pending_id,)
        )
        get_db().commit()
    except PhoneVerificationError as error:
        get_db().commit()
        flash(str(error), "error")
        return render_template(
            "auth.html",
            mode="register",
            country_codes=COUNTRY_CODES,
            verification_sent=True,
            masked_phone=mask_phone(pending["normalized_phone"]),
            form_values=dict(pending),
        )
    except sqlite3.IntegrityError:
        get_db().rollback()
        flash(
            "That email or mobile number is already registered.",
            "error",
        )
        return render_template(
            "auth.html",
            mode="register",
            country_codes=COUNTRY_CODES,
            verification_sent=True,
            masked_phone=mask_phone(pending["normalized_phone"]),
            form_values=dict(pending),
        )
    session.clear()
    session["user_id"] = user_id
    flash("Mobile number verified. Your Khattah account is ready.", "success")
    return redirect(url_for("dashboard"))


@app.post("/register/resend")
def register_resend():
    pending_id = session.get("pending_registration_id")
    pending = get_db().execute(
        "SELECT * FROM pending_registrations WHERE id = ?", (pending_id,)
    ).fetchone()
    if pending is None:
        flash("Start registration before requesting another code.", "error")
        return redirect(url_for("register"))
    try:
        challenge = request_phone_verification(
            get_db(),
            pending["country_calling_code"],
            pending["mobile_number"],
            pending_registration_id=pending_id,
        )
        get_db().commit()
        session["phone_challenge_token"] = challenge["challenge_token"]
        flash("A new mock verification code was requested.", "success")
    except PhoneVerificationError as error:
        get_db().rollback()
        flash(str(error), "error")
    return render_template(
        "auth.html",
        mode="register",
        country_codes=COUNTRY_CODES,
        verification_sent=True,
        masked_phone=mask_phone(pending["normalized_phone"]),
        form_values=dict(pending),
    )


@app.route("/login", methods=("GET", "POST"))
def login():
    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")
        user = get_db().execute("SELECT * FROM users WHERE email = ?", (email,)).fetchone()
        demo_account_blocked = (
            email in {"demo@khattah.test", "admin@khattah.test"}
            and not app.config["SEED_DEMO_DATA"]
        )
        if (
            user is None
            or demo_account_blocked
            or not check_password_hash(user["password_hash"], password)
        ):
            flash("Those sign-in details do not match our records.", "error")
            return render_template("auth.html", mode="login")
        session.clear()
        session["user_id"] = user["id"]
        next_path = request.args.get("next", "")
        return redirect(next_path if next_path.startswith("/") and not next_path.startswith("//") else url_for("dashboard"))
    return render_template("auth.html", mode="login")


def _demo_login(email, destination):
    if not app.config["SEED_DEMO_DATA"]:
        return "Not found", 404
    user = get_db().execute("SELECT id FROM users WHERE email = ?", (email,)).fetchone()
    if user is None:
        return "Not found", 404
    session.clear()
    session["user_id"] = user["id"]
    return redirect(url_for(destination))


@app.get("/demo")
def demo_login():
    return _demo_login("demo@khattah.test", "dashboard")


@app.get("/demo/admin")
def demo_admin_login():
    return _demo_login("admin@khattah.test", "admin_invitation_messages")


@app.get("/logout")
def logout():
    session.clear()
    flash("You have been signed out.", "info")
    return redirect(url_for("welcome"))


@app.get("/dashboard")
@login_required
def dashboard():
    return render_template(
        "dashboard.html", page="dashboard", data=get_dashboard(get_db(), session["user_id"])
    )


@app.get("/packages")
@login_required
def packages():
    return render_template(
        "packages.html", page="packages", data=get_package(get_db(), session["user_id"])
    )


@app.post("/packages/new")
@login_required
def packages_new():
    result = start_new_package(get_db(), session["user_id"])
    get_db().commit()
    flash(
        f"Package #{result['package']['sequence_number']} is ready."
        if result["created"]
        else "You already have an active package.",
        "success" if result["created"] else "info",
    )
    return redirect(url_for("packages"))


@app.get("/circle")
@login_required
def circle_compatibility():
    """Legacy Circle URL retained as a redirect to canonical Packages."""
    return redirect(url_for("packages"))


@app.post("/circle/new")
@login_required
def circle_new_compatibility():
    """Legacy Circle URL retained for existing forms and bookmarks."""
    return packages_new()


@app.route("/invitations", methods=("GET", "POST"))
@login_required
def invitations():
    if request.method == "POST":
        recipient = request.form.get("recipient", "").strip()
        message_id = request.form.get("invitation_message_id", type=int)
        if not recipient:
            flash("Add an email address or phone number to send an invitation.", "error")
        elif message_id is None and available_messages(get_db()):
            flash("Select an approved invitation message.", "error")
        else:
            message = get_message(get_db(), message_id)
            if message is None or not message["is_approved"] or not message["is_active"] or message["is_archived"]:
                flash("That invitation message is not available.", "error")
                return redirect(url_for("invitations"))
            create_invitation(get_db(), session["user_id"], recipient, message_id)
            get_db().commit()
            flash("Invitation added to your list.", "success")
        return redirect(url_for("invitations"))
    invitations_data = get_invitations(get_db(), session["user_id"])
    for invite in invitations_data:
        if invite.get("invitation_message_id"):
            message = get_message(get_db(), invite["invitation_message_id"])
            if message and message["is_approved"] and message["is_active"] and not message["is_archived"]:
                token = make_invite_token(app.config["SECRET_KEY"], invite["id"], session["user_id"])
                link = url_for("public_invitation", token=token, _external=True)
                invite["invite_link"] = link
                invite["rendered_message"] = render_message(message, current_user()["name"], link)
                rendered = invite["rendered_message"]
                share_text = rendered["body"]
                if link not in share_text:
                    share_text = f"{share_text}\n{link}"
                invite["share_text"] = share_text
                invite["share_channel"] = message["channel"]
    return render_template(
        "invitations.html",
        page="invitations",
        data=invitations_data,
        messages=available_messages(get_db()),
    )


@app.get("/transactions")
@login_required
def transactions():
    return render_template(
        "transactions.html",
        page="transactions",
        data=get_transactions(get_db(), session["user_id"]),
    )


@app.get("/rewards")
@login_required
def rewards():
    return render_template(
        "rewards.html", page="rewards", data=get_rewards(get_db(), session["user_id"])
    )


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
    return render_template(
        "profile.html", page="profile", data=get_profile(get_db(), session["user_id"])
    )


@app.route("/settings", methods=("GET", "POST"))
@login_required
def settings():
    if request.method == "POST":
        preferred_language = normalize_language(
            request.form.get("preferred_language", "en")
        )
        update_settings(
            get_db(),
            session["user_id"],
            bool(request.form.get("email_notifications")),
            bool(request.form.get("invitation_reminders")),
            preferred_language,
        )
        get_db().commit()
        session["language"] = preferred_language
        g.language = preferred_language
        flash("Settings saved.", "success")
        return redirect(url_for("settings"))
    return render_template(
        "settings.html", page="settings", data=get_settings(get_db(), session["user_id"])
    )


@app.get("/admin")
@admin_required
def admin():
    return render_template("admin.html", page="admin", data=get_admin_overview(get_db()),
                           invitation_messages=list_messages(get_db(), include_archived=True))


@app.route("/admin/appearance", methods=("GET", "POST"))
@admin_required
def admin_appearance():
    database = get_db()
    if request.method == "POST":
        try:
            action = request.form.get("action", "")
            if action == "activate":
                activate_appearance(database, request.form.get("kind"), request.form.get("template"), session["user_id"])
            elif action == "colors":
                save_colors(database, request.form.get("template"), request.form, session["user_id"])
            elif action == "reset":
                reset_colors(database, request.form.get("template"), session["user_id"])
            elif action == "package":
                save_package(database, request.form, session["user_id"])
            else:
                raise ValueError("Unknown appearance action.")
            database.commit()
            flash("Appearance settings saved.", "success")
            return redirect(url_for("admin_appearance"))
        except (ValueError, TypeError) as error:
            database.rollback()
            flash(str(error), "error")
    return render_template("admin_appearance.html", page="admin",
                           appearance={**get_appearance_settings(database),
                                       "template_key": g.appearance["template_key"],
                                       "theme_scope": g.appearance["theme_scope"],
                                       "colors": g.appearance["colors"]},
                           colors=list_colors(database),
                           packages=list_package_display(database),
                           audit_rows=appearance_audit_rows(database),
                           template_keys=TEMPLATE_KEYS, color_fields=COLOR_FIELDS,
                           palettes=DEFAULT_PALETTES, icons=ICON_ALLOWLIST)


@app.get("/admin/invitation-messages")
@admin_required
def admin_invitation_messages():
    rows = list_messages(get_db(), include_archived=True)
    return render_template("admin_invitation_messages.html", page="admin",
                           messages=rows,
                           audit_rows=get_message_audit(get_db()))


@app.post("/admin/invitations/<int:invitation_id>/activate")
@admin_required
def admin_activate(invitation_id):
    try:
        result = activate_invitation(get_db(), invitation_id, session["user_id"])
        get_db().commit()
    except ValueError as error:
        get_db().rollback()
        flash(str(error), "error")
    else:
        if not result["changed"]:
            flash(result["message"], "info")
        elif result["package_completed"]:
            flash("Mock activation recorded. The package completed and a reward is available.", "success")
        elif result["qualified"]:
            flash("Mock activation recorded and the participant qualified.", "success")
        else:
            flash(result.get("message", "No change was needed."), "info")
    return redirect(url_for("admin"))


@app.post("/admin/invitation-messages")
@admin_required
def admin_message_create():
    try:
        create_message(get_db(), session["user_id"], request.form)
        get_db().commit()
        flash("Invitation message created.", "success")
    except ValueError as error:
        get_db().rollback()
        flash(str(error), "error")
    return redirect(url_for("admin"))


@app.route("/admin/invitation-messages/<int:message_id>/edit", methods=("GET", "POST"))
@admin_required
def admin_message_edit(message_id):
    message = get_message(get_db(), message_id)
    if message is None:
        return render_template("404.html"), 404
    if request.method == "POST":
        try:
            update_message(get_db(), message_id, session["user_id"], request.form)
            get_db().commit()
            flash("Invitation message updated.", "success")
            return redirect(url_for("admin_invitation_messages"))
        except ValueError as error:
            get_db().rollback()
            flash(str(error), "error")
    return render_template("admin_invitation_message_edit.html", page="admin",
                           message=message)


@app.post("/admin/invitation-messages/<int:message_id>/<action>")
@admin_required
def admin_message_action(message_id, action):
    try:
        set_message_state(get_db(), message_id, session["user_id"], action)
        get_db().commit()
        flash("Invitation message updated.", "success")
    except ValueError as error:
        get_db().rollback()
        flash(str(error), "error")
    return redirect(url_for("admin"))


@app.errorhandler(404)
def not_found(_error):
    return render_template("404.html"), 404


@app.get("/api/v1/me")
@api_login_required
def api_me():
    return jsonify(get_profile(get_db(), session["user_id"]))


@app.get("/api/v1/csrf")
@api_login_required
def api_csrf():
    return jsonify({"csrf_token": session["csrf_token"]})


@app.post("/api/v1/phone-verification/request")
def api_phone_verification_request():
    payload = request.get_json(silent=True) or {}
    try:
        record_phone_api_request()
        challenge = request_phone_verification(
            get_db(),
            payload.get("country_code", ""),
            payload.get("mobile_number", ""),
        )
        get_db().commit()
    except VerificationRateLimitError as error:
        get_db().rollback()
        return api_error(str(error), 429)
    except DuplicatePhoneError as error:
        get_db().rollback()
        return api_error(str(error), 409)
    except PhoneVerificationError as error:
        get_db().rollback()
        return api_error(str(error), 400)
    return jsonify(
        {
            "challenge_token": challenge["challenge_token"],
            "masked_phone": challenge["masked_phone"],
            "delivery": challenge["delivery"],
            "expires_in_seconds": 600,
            "resend_after_seconds": 60,
        }
    ), 201


@app.post("/api/v1/phone-verification/verify")
def api_phone_verification_verify():
    payload = request.get_json(silent=True) or {}
    try:
        result = verify_code(
            get_db(),
            str(payload.get("challenge_token", "")),
            str(payload.get("verification_code", "")),
        )
        get_db().commit()
    except PhoneVerificationError as error:
        get_db().commit()
        return api_error(str(error), 400)
    return jsonify(
        {
            "verified": result["verified"],
            "already_verified": result["already_verified"],
            "verified_at": result["verified_at"],
        }
    )


@app.get("/api/v1/dashboard")
@api_login_required
def api_dashboard():
    return jsonify(get_dashboard(get_db(), session["user_id"]))


@app.get("/api/v1/circle")
@api_login_required
def api_circle():
    return jsonify(get_circle(get_db(), session["user_id"]))


@app.get("/api/v1/circles")
@api_login_required
def api_circle_history():
    return jsonify(get_circle_history(get_db(), session["user_id"]))


@app.post("/api/v1/circles")
@api_login_required
def api_circle_create():
    result = start_new_circle(get_db(), session["user_id"])
    get_db().commit()
    return jsonify(result), 201 if result["created"] else 200


_PACKAGE_KEY_ALIASES = {
    "circle": "package",
    "circles": "packages",
    "circle_id": "package_id",
    "circle_status": "package_status",
    "current": "current_package",
    "history": "package_history",
    "completed_circle_count": "completed_package_count",
    "circle_count": "package_count",
}


def _canonical_package_json(value):
    """Return a recursively package-only API representation."""
    if isinstance(value, list):
        return [_canonical_package_json(item) for item in value]
    if not isinstance(value, dict):
        return value
    # Canonical source keys always win over compatibility aliases, regardless
    # of the order in which a service assembled its response dictionary.
    explicit_keys = set(value) - set(_PACKAGE_KEY_ALIASES)
    result = {}
    for key, item in value.items():
        if key in _PACKAGE_KEY_ALIASES and _PACKAGE_KEY_ALIASES[key] in explicit_keys:
            continue
        canonical_key = _PACKAGE_KEY_ALIASES.get(key, key)
        if "circle" in canonical_key.lower():
            continue
        # Canonical names already present win over compatibility aliases.
        if canonical_key in result:
            continue
        result[canonical_key] = _canonical_package_json(item)
    return result


@app.get("/api/v1/package")
@api_login_required
def api_package():
    return jsonify(_canonical_package_json(get_package(get_db(), session["user_id"])))


@app.get("/api/v1/packages")
@api_login_required
def api_packages():
    history = get_package_history(get_db(), session["user_id"])
    return jsonify(_canonical_package_json({"packages": history}))


@app.post("/api/v1/packages")
@api_login_required
def api_package_create():
    result = start_new_package(get_db(), session["user_id"])
    get_db().commit()
    return jsonify(_canonical_package_json(result)), 201 if result["created"] else 200


@app.route("/api/v1/invitations", methods=("GET", "POST"))
@api_login_required
def api_invitations():
    if request.method == "POST":
        payload = request.get_json(silent=True) or {}
        recipient = str(payload.get("recipient", "")).strip()
        if not recipient:
            return api_error("recipient is required", 400)
        message_id = payload.get("invitation_message_id")
        if message_id is None:
            return api_error("invitation message is required", 400)
        if message_id is not None:
            message = get_message(get_db(), message_id)
            if message is None or not message["is_approved"] or not message["is_active"] or message["is_archived"]:
                return api_error("invitation message is not available", 400)
        invitation = create_invitation(get_db(), session["user_id"], recipient, message_id)
        get_db().commit()
        return jsonify(dict(invitation)), 201
    return jsonify(get_invitations(get_db(), session["user_id"]))


@app.get("/api/v1/transactions")
@api_login_required
def api_transactions():
    return jsonify(get_transactions(get_db(), session["user_id"]))


@app.get("/api/v1/rewards")
@api_login_required
def api_rewards():
    return jsonify(get_rewards(get_db(), session["user_id"]))


@app.route("/api/v1/profile", methods=("GET", "PATCH"))
@api_login_required
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
@api_login_required
def api_settings():
    if request.method == "PATCH":
        payload = request.get_json(silent=True) or {}
        update_settings(
            get_db(),
            session["user_id"],
            bool(payload.get("email_notifications", True)),
            bool(payload.get("invitation_reminders", True)),
            normalize_language(str(payload.get("preferred_language", "en"))),
        )
        get_db().commit()
    return jsonify(get_settings(get_db(), session["user_id"]))


@app.get("/api/v1/admin/overview")
@api_admin_required
def api_admin_overview():
    return jsonify(get_admin_overview(get_db()))


@app.get("/api/v1/admin/appearance")
@api_admin_required
def api_admin_appearance():
    database = get_db()
    settings = get_appearance_settings(database)
    return jsonify({"settings": settings, "colors": list_colors(database),
                    "packages": list_package_display(database),
                    "audit": appearance_audit_rows(database)})


@app.patch("/api/v1/admin/appearance")
@app.post("/api/v1/admin/appearance/activate")
@app.post("/api/v1/admin/appearance/colors")
@app.post("/api/v1/admin/appearance/packages")
@api_admin_required
def api_admin_appearance_update():
    database = get_db()
    payload = request.get_json(silent=True) or {}
    try:
        actor = session["user_id"]
        action = payload.get("action")
        if request.path.endswith("/activate"):
            action = "activate"
        elif request.path.endswith("/colors"):
            action = "colors"
        elif request.path.endswith("/packages"):
            action = "package"
        if action == "activate":
            activate_appearance(database, payload.get("kind"), payload.get("template"), actor)
        elif action == "colors":
            save_colors(database, payload.get("template"), payload.get("colors", {}), actor)
        elif payload.get("action") == "reset":
            reset_colors(database, payload.get("template"), actor)
        elif payload.get("action") == "package":
            save_package(database, payload, actor)
        else:
            raise ValueError("Unknown appearance action.")
        database.commit()
        return jsonify({"settings": get_appearance_settings(database),
                        "colors": list_colors(database),
                        "packages": list_package_display(database)})
    except (ValueError, TypeError, KeyError) as error:
        database.rollback()
        return api_error(str(error), 400)


@app.get("/api/v1/invitation-messages")
@api_login_required
def api_invitation_messages():
    rows = available_messages(get_db()) if not current_user()["is_admin"] else list_messages(get_db(), include_archived=True)
    return jsonify([dict(row) for row in rows])


@app.post("/api/v1/admin/invitation-messages")
@api_admin_required
def api_admin_message_create():
    try:
        row = create_message(get_db(), session["user_id"], request.get_json(silent=True) or {})
        get_db().commit()
        return jsonify(dict(row)), 201
    except ValueError as error:
        get_db().rollback()
        return api_error(str(error), 400)


@app.post("/api/v1/admin/invitation-messages/preview")
@api_admin_required
def api_admin_message_preview():
    payload = request.get_json(silent=True) or {}
    try:
        from services.invitation_messages import validate_message
        validate_message(payload.get("channel"), payload.get("language"),
                         payload.get("subject", ""), payload.get("body"))
        return jsonify({
            "channel": payload["channel"], "language": payload["language"],
            "subject": (payload.get("subject") or "").format(
                inviter_name=payload.get("inviter_name", "Inviter"),
                invite_link=payload.get("invite_link", "{invite_link}")),
            "body": payload["body"].format(
                inviter_name=payload.get("inviter_name", "Inviter"),
                invite_link=payload.get("invite_link", "{invite_link}")),
        })
    except (ValueError, KeyError) as error:
        return api_error(str(error), 400)


@app.route("/api/v1/admin/invitation-messages/<int:message_id>", methods=("PATCH", "GET"))
@api_admin_required
def api_admin_message(message_id):
    row = get_message(get_db(), message_id)
    if row is None:
        return api_error("invitation message not found", 404)
    if request.method == "GET":
        return jsonify(dict(row))
    try:
        row = update_message(get_db(), message_id, session["user_id"], request.get_json(silent=True) or {})
        get_db().commit()
        return jsonify(dict(row))
    except ValueError as error:
        get_db().rollback()
        return api_error(str(error), 400)


@app.post("/api/v1/admin/invitation-messages/<int:message_id>/<action>")
@api_admin_required
def api_admin_message_action(message_id, action):
    try:
        row = set_message_state(get_db(), message_id, session["user_id"], action)
        get_db().commit()
        return jsonify(dict(row))
    except ValueError as error:
        get_db().rollback()
        return api_error(str(error), 400)


@app.get("/api/v1/invitations/<int:invitation_id>/share")
@api_login_required
def api_invitation_share(invitation_id):
    invitation = get_db().execute(
        "SELECT * FROM invitations WHERE id=? AND user_id=?",
        (invitation_id, session["user_id"])).fetchone()
    if invitation is None:
        return api_error("invitation not found", 404)
    if not invitation["invitation_message_id"]:
        return api_error("invitation has no message", 400)
    message = get_message(get_db(), invitation["invitation_message_id"])
    if message is None or not message["is_approved"] or not message["is_active"] or message["is_archived"]:
        return api_error("invitation message is not available", 400)
    token = make_invite_token(app.config["SECRET_KEY"], invitation_id, session["user_id"])
    link = url_for("public_invitation", token=token, _external=True)
    rendered = render_message(message, current_user()["name"], link)
    share_text = rendered["body"] if link in rendered["body"] else f"{rendered['body']}\n{link}"
    return jsonify(rendered | {"share_text": share_text,
        "channel": message["channel"], "language": message["language"], "invite_link": link})


@app.get("/invite/<token>")
def public_invitation(token):
    payload = read_invite_token(app.config["SECRET_KEY"], token)
    if not payload:
        return render_template("public_invitation.html", invalid=True), 404
    invitation = get_db().execute(
        """SELECT i.*, u.name AS inviter_name FROM invitations i
           JOIN users u ON u.id=i.user_id WHERE i.id=? AND i.user_id=?""",
        (payload.get("invitation_id"), payload.get("owner_id")),
    ).fetchone()
    if invitation is None:
        return render_template("public_invitation.html", invalid=True), 404
    message = get_message(get_db(), invitation["invitation_message_id"]) if invitation["invitation_message_id"] else None
    if message is not None and (not message["is_approved"] or not message["is_active"] or message["is_archived"]):
        message = None
    rendered = render_message(message, invitation["inviter_name"], request.url) if message else None
    return render_template("public_invitation.html", invalid=False, invitation=invitation, message=rendered)


@app.post("/api/v1/admin/invitations/<int:invitation_id>/activate")
@api_admin_required
def api_admin_activate(invitation_id):
    try:
        result = activate_invitation(get_db(), invitation_id, session["user_id"])
        get_db().commit()
        return jsonify(result)
    except ValueError as error:
        get_db().rollback()
        return api_error(str(error), 404)


if __name__ == "__main__":
    with app.app_context():
        init_db()
    port = int(os.environ.get("PORT", "5000"))
    app.run(host="0.0.0.0", port=port, debug=False, use_reloader=False)