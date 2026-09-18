from datetime import datetime


STATUS_META = {
    "registered": {"label": "Registered", "tone": "yellow"},
    "invited": {"label": "Invited", "tone": "yellow"},
    "paid": {"label": "Paid", "tone": "green"},
    "activated": {"label": "Activated", "tone": "green"},
    "eligible": {"label": "Eligible to redeem", "tone": "red"},
    "completed": {"label": "Completed", "tone": "blue"},
}


def as_status(value):
    meta = STATUS_META.get(value, {"label": value.title(), "tone": "neutral"})
    return {"key": value, **meta}


def serialize_row(row):
    return dict(row) if row is not None else None


def get_dashboard(database, user_id):
    user = database.execute(
        "SELECT id, name, email, status FROM users WHERE id = ?", (user_id,)
    ).fetchone()
    invitation_count = database.execute(
        "SELECT COUNT(*) AS count FROM invitations WHERE user_id = ?", (user_id,)
    ).fetchone()["count"]
    activities = database.execute(
        """
        SELECT id, type, description, status, occurred_at
        FROM transactions
        WHERE user_id = ?
        ORDER BY occurred_at DESC
        LIMIT 4
        """,
        (user_id,),
    ).fetchall()
    return {
        "member": {**serialize_row(user), "status": as_status(user["status"])},
        "account_status": as_status(user["status"]),
        "circle_status": {"label": "Rules not configured", "tone": "neutral"},
        "qualifying_participants": {
            "value": 0,
            "label": "Awaiting your Khattah rules",
        },
        "invitation_count": invitation_count,
        "payment_status": {"label": "Not configured", "tone": "neutral"},
        "reward_status": {"label": "Not configured", "tone": "neutral"},
        "recent_activity": [
            {
                "id": item["id"],
                "type": item["type"],
                "description": item["description"],
                "status": item["status"],
                "occurred_at": item["occurred_at"],
            }
            for item in activities
        ],
    }


def get_circle(database, user_id):
    members = database.execute(
        """
        SELECT id, name, initials, status, invited_at
        FROM circle_members
        WHERE user_id = ?
        ORDER BY invited_at DESC
        """,
        (user_id,),
    ).fetchall()
    return {
        "name": "My circle",
        "status": {"label": "Rules not configured", "tone": "neutral"},
        "target_description": "Qualifying participant rules will be added after you define them.",
        "qualifying_participants": {"value": 0, "label": "Not calculated yet"},
        "participants": [
            {
                **serialize_row(member),
                "status": as_status(member["status"]),
            }
            for member in members
        ],
    }


def get_invitations(database, user_id):
    rows = database.execute(
        """
        SELECT id, recipient, status, sent_at
        FROM invitations
        WHERE user_id = ?
        ORDER BY sent_at DESC
        """,
        (user_id,),
    ).fetchall()
    return [serialize_row(row) for row in rows]


def get_transactions(database, user_id):
    rows = database.execute(
        """
        SELECT id, type, description, status, amount_label, occurred_at
        FROM transactions
        WHERE user_id = ?
        ORDER BY occurred_at DESC
        """,
        (user_id,),
    ).fetchall()
    return [
        {
            **serialize_row(row),
            "formatted_date": _format_date(row["occurred_at"]),
        }
        for row in rows
    ]


def get_profile(database, user_id):
    row = database.execute(
        """
        SELECT id, name, email, phone, status, joined_at
        FROM users
        WHERE id = ?
        """,
        (user_id,),
    ).fetchone()
    profile = serialize_row(row)
    profile["status"] = as_status(row["status"])
    return profile


def update_profile(database, user_id, name, phone):
    if name:
        database.execute(
            "UPDATE users SET name = ?, phone = ? WHERE id = ?",
            (name, phone, user_id),
        )


def get_settings(database, user_id):
    row = database.execute(
        """
        SELECT email_notifications, invitation_reminders, preferred_language
        FROM settings
        WHERE user_id = ?
        """,
        (user_id,),
    ).fetchone()
    return {
        "email_notifications": bool(row["email_notifications"]),
        "invitation_reminders": bool(row["invitation_reminders"]),
        "preferred_language": row["preferred_language"],
    }


def update_settings(database, user_id, email_notifications, invitation_reminders, preferred_language):
    database.execute(
        """
        UPDATE settings
        SET email_notifications = ?, invitation_reminders = ?, preferred_language = ?
        WHERE user_id = ?
        """,
        (int(email_notifications), int(invitation_reminders), preferred_language, user_id),
    )


def _format_date(value):
    try:
        return datetime.fromisoformat(value).strftime("%b %-d, %Y")
    except (TypeError, ValueError):
        return value