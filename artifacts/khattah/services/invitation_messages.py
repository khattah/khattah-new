"""Admin-controlled, bilingual invitation message catalogue."""
import re
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer

CHANNELS = ("whatsapp", "sms", "email", "facebook", "messenger", "telegram", "x", "general")
LANGUAGES = ("en", "ar")
ALLOWED_PLACEHOLDERS = {"inviter_name", "invite_link"}
_PLACEHOLDER_RE = re.compile(r"\{([A-Za-z_][A-Za-z0-9_]*)\}")


def validate_message(channel, language, subject, body):
    if channel not in CHANNELS:
        raise ValueError("invalid invitation message channel")
    if language not in LANGUAGES:
        raise ValueError("invalid invitation message language")
    if not str(body or "").strip():
        raise ValueError("message body is required")
    names = set(_PLACEHOLDER_RE.findall(f"{subject or ''}\n{body}"))
    unsupported = names - ALLOWED_PLACEHOLDERS
    if unsupported:
        raise ValueError("unsupported message placeholder")


def list_messages(database, include_archived=False, approved_only=False):
    sql = "SELECT * FROM invitation_messages WHERE 1=1"
    args = []
    if not include_archived:
        sql += " AND is_archived = 0"
    if approved_only:
        sql += " AND is_approved = 1 AND is_active = 1"
    sql += " ORDER BY channel, language, id DESC"
    return database.execute(sql, args).fetchall()


def available_messages(database):
    return list_messages(database, approved_only=True)


def get_message(database, message_id):
    return database.execute(
        "SELECT * FROM invitation_messages WHERE id = ?", (message_id,)
    ).fetchone()


def get_message_audit(database, message_id=None):
    sql = """SELECT a.*, u.name AS actor_name
             FROM invitation_message_audit a
             JOIN users u ON u.id = a.actor_user_id"""
    args = []
    if message_id is not None:
        sql += " WHERE a.message_id = ?"
        args.append(message_id)
    sql += " ORDER BY a.occurred_at DESC, a.id DESC"
    return database.execute(sql, args).fetchall()


def audit(database, message_id, actor_id, action, details=""):
    database.execute(
        """INSERT INTO invitation_message_audit
           (message_id, actor_user_id, action, occurred_at, details)
           VALUES (?, ?, ?, datetime('now'), ?)""",
        (message_id, actor_id, action, details),
    )


def create_message(database, actor_id, values):
    validate_message(values.get("channel"), values.get("language"),
                     values.get("subject", ""), values.get("body"))
    cursor = database.execute(
        """INSERT INTO invitation_messages
           (campaign_name, channel, language, subject, body, created_by_user_id,
            updated_by_user_id, created_at, updated_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, datetime('now'), datetime('now'))""",
        (values.get("campaign_name", "").strip() or "Invitation campaign",
         values["channel"], values["language"], values.get("subject", "").strip(),
         values["body"].strip(), actor_id, actor_id),
    )
    audit(database, cursor.lastrowid, actor_id, "created")
    return get_message(database, cursor.lastrowid)


def update_message(database, message_id, actor_id, values):
    old = get_message(database, message_id)
    if old is None:
        raise ValueError("invitation message not found")
    if old["is_archived"]:
        raise ValueError("archived messages are terminal")
    validate_message(values.get("channel"), values.get("language"),
                     values.get("subject", ""), values.get("body"))
    wording_changed = any(values.get(key, "") != old[key] for key in
                          ("channel", "language", "subject", "body"))
    database.execute(
        """UPDATE invitation_messages
           SET campaign_name=?, channel=?, language=?, subject=?, body=?,
               updated_by_user_id=?, updated_at=datetime('now'),
               is_approved=CASE WHEN ? THEN 0 ELSE is_approved END,
               is_active=CASE WHEN ? THEN 0 ELSE is_active END,
               approved_by_user_id=CASE WHEN ? THEN NULL ELSE approved_by_user_id END,
               activated_by_user_id=CASE WHEN ? THEN NULL ELSE activated_by_user_id END,
               approved_at=CASE WHEN ? THEN NULL ELSE approved_at END,
               activated_at=CASE WHEN ? THEN NULL ELSE activated_at END
           WHERE id=?""",
        (values.get("campaign_name", "").strip() or "Invitation campaign",
         values["channel"], values["language"], values.get("subject", "").strip(),
         values["body"].strip(), actor_id, int(wording_changed), int(wording_changed),
         int(wording_changed), int(wording_changed), int(wording_changed),
         int(wording_changed), message_id),
    )
    audit(database, message_id, actor_id, "updated",
          "approval reset" if wording_changed else "")
    return get_message(database, message_id)


def set_message_state(database, message_id, actor_id, action):
    row = get_message(database, message_id)
    if row is None:
        raise ValueError("invitation message not found")
    if row["is_archived"] and action in {"approve", "activate", "deactivate"}:
        raise ValueError("archived messages are terminal")
    if action == "approve":
        database.execute("""UPDATE invitation_messages SET is_approved=1,
            approved_by_user_id=?, approved_at=datetime('now') WHERE id=?""",
                        (actor_id, message_id))
    elif action == "activate":
        if not row["is_approved"] or row["is_archived"]:
            raise ValueError("message must be approved and not archived before activation")
        database.execute("""UPDATE invitation_messages SET is_active=1,
            activated_by_user_id=?, activated_at=datetime('now') WHERE id=?""",
                        (actor_id, message_id))
    elif action == "deactivate":
        database.execute("""UPDATE invitation_messages SET is_active=0,
            activated_by_user_id=NULL, activated_at=NULL WHERE id=?""", (message_id,))
    elif action == "archive":
        database.execute("""UPDATE invitation_messages SET is_archived=1,
            is_active=0, activated_by_user_id=NULL, activated_at=NULL,
            archived_at=COALESCE(archived_at, datetime('now')) WHERE id=?""", (message_id,))
    else:
        raise ValueError("invalid invitation message action")
    audit(database, message_id, actor_id, action)
    return get_message(database, message_id)


def make_invite_token(secret_key, invitation_id, owner_id):
    return URLSafeTimedSerializer(secret_key, salt="khattah-invitation").dumps(
        {"invitation_id": invitation_id, "owner_id": owner_id})


def read_invite_token(secret_key, token, max_age=60 * 60 * 24 * 30):
    try:
        return URLSafeTimedSerializer(secret_key, salt="khattah-invitation").loads(
            token, max_age=max_age)
    except (BadSignature, SignatureExpired):
        return None


def render_message(message, inviter_name, invite_link):
    values = {"inviter_name": inviter_name, "invite_link": invite_link}
    return {**dict(message),
            "subject": (message["subject"] or "").format(**values),
            "body": message["body"].format(**values)}