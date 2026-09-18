from datetime import datetime, timezone


# Package terminology is canonical in the application layer. The persistence
# schema still uses the historical circle_* names for data compatibility.
PACKAGE_SIZE = 5
CIRCLE_SIZE = PACKAGE_SIZE  # Compatibility alias for existing callers.
QUALIFICATION_POLICY = "first_five_activated"

STATUS_META = {
    "invited": {"label": "Invited", "tone": "yellow"},
    "pending": {"label": "Invited", "tone": "yellow"},
    "opened": {"label": "Invited", "tone": "yellow"},
    "registered": {"label": "Registered", "tone": "yellow"},
    "joined": {"label": "Registered", "tone": "yellow"},
    "paid": {"label": "Paid / Activated", "tone": "green"},
    "activated": {"label": "Paid / Activated", "tone": "green"},
    "qualified": {"label": "Qualified", "tone": "green"},
    "active": {"label": "Active", "tone": "green"},
    "eligible": {"label": "Reward Available", "tone": "blue"},
    "available": {"label": "Reward Available", "tone": "blue"},
    "completed": {"label": "Completed", "tone": "red"},
}


def utc_now():
    return datetime.now(timezone.utc).isoformat()


def as_status(value):
    meta = STATUS_META.get(value, {"label": value.replace("_", " ").title(), "tone": "neutral"})
    return {"key": value, **meta}


def serialize_row(row):
    return dict(row) if row is not None else None


def record_event(database, user_id, event_type, description, entity_type=None, entity_id=None):
    database.execute(
        """
        INSERT INTO audit_events
            (user_id, event_type, description, entity_type, entity_id, occurred_at)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (user_id, event_type, description, entity_type, entity_id, utc_now()),
    )


def record_transaction(database, user_id, event_type, description, status):
    database.execute(
        """
        INSERT INTO transactions
            (user_id, type, description, status, amount_label, occurred_at)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (user_id, event_type, description, status, "No amount configured", utc_now()),
    )


def ensure_active_circle(database, user_id):
    circle = database.execute(
        """
        SELECT * FROM circles
        WHERE user_id = ? AND status = 'active'
        ORDER BY sequence_number DESC
        LIMIT 1
        """,
        (user_id,),
    ).fetchone()
    if circle is not None:
        return circle
    sequence = database.execute(
        "SELECT COALESCE(MAX(sequence_number), 0) + 1 AS next_number FROM circles WHERE user_id = ?",
        (user_id,),
    ).fetchone()["next_number"]
    cursor = database.execute(
        """
        INSERT INTO circles
            (user_id, sequence_number, status, required_participants, created_at)
        VALUES (?, ?, 'active', ?, ?)
        """,
        (user_id, sequence, CIRCLE_SIZE, utc_now()),
    )
    circle_id = cursor.lastrowid
    record_event(
        database,
        user_id,
        "circle_created",
        f"Package #{sequence} created",
        "circle",
        circle_id,
    )
    return database.execute("SELECT * FROM circles WHERE id = ?", (circle_id,)).fetchone()


def start_new_circle(database, user_id):
    existing = database.execute(
        "SELECT id FROM circles WHERE user_id = ? AND status = 'active'",
        (user_id,),
    ).fetchone()
    if existing is not None:
        return {"created": False, "circle": get_circle_by_id(database, existing["id"])}
    circle = ensure_active_circle(database, user_id)
    return {"created": True, "circle": get_circle_by_id(database, circle["id"])}


def create_invitation(database, user_id, recipient, invitation_message_id=None):
    cursor = database.execute(
        """
        INSERT INTO invitations (user_id, recipient, status, sent_at, invitation_message_id)
        VALUES (?, ?, 'pending', ?, ?)
        """,
        (user_id, recipient, utc_now()[:10], invitation_message_id),
    )
    invitation_id = cursor.lastrowid
    record_event(
        database,
        user_id,
        "invitation_created",
        f"Invitation sent to {recipient}",
        "invitation",
        invitation_id,
    )
    return database.execute(
        "SELECT id, user_id, recipient, status, sent_at, invitation_message_id FROM invitations WHERE id = ?",
        (invitation_id,),
    ).fetchone()


def activate_invitation(database, invitation_id, administrator_id):
    invitation = database.execute(
        "SELECT * FROM invitations WHERE id = ?", (invitation_id,)
    ).fetchone()
    if invitation is None:
        raise ValueError("Invitation not found")

    existing = database.execute(
        "SELECT id FROM activations WHERE invitation_id = ?", (invitation_id,)
    ).fetchone()
    if existing is not None:
        return {
            "changed": False,
            "message": "This invitation is already activated.",
            "circle": get_current_or_latest_circle(database, invitation["user_id"]),
        }

    owner_id = invitation["user_id"]
    activated_at = utc_now()
    activation_cursor = database.execute(
        """
        INSERT INTO activations
            (invitation_id, user_id, marked_by_user_id, status, activated_at)
        VALUES (?, ?, ?, 'paid', ?)
        """,
        (invitation_id, owner_id, administrator_id, activated_at),
    )
    database.execute(
        "UPDATE invitations SET status = 'paid' WHERE id = ?", (invitation_id,)
    )
    record_event(
        database,
        owner_id,
        "activation_recorded",
        f"{invitation['recipient']} marked paid / activated",
        "activation",
        activation_cursor.lastrowid,
    )
    record_transaction(
        database,
        owner_id,
        "Activation",
        f"{invitation['recipient']} was activated",
        "Paid / Activated",
    )

    circle = ensure_active_circle(database, owner_id)
    qualified_count = database.execute(
        "SELECT COUNT(*) AS count FROM circle_participants WHERE circle_id = ? AND status = 'qualified'",
        (circle["id"],),
    ).fetchone()["count"]
    qualified = False

    if qualified_count < circle["required_participants"]:
        position = qualified_count + 1
        database.execute(
            """
            INSERT INTO circle_participants
                (circle_id, invitation_id, position_number, status, qualified_at)
            VALUES (?, ?, ?, 'qualified', ?)
            """,
            (circle["id"], invitation_id, position, activated_at),
        )
        qualified = True
        record_event(
            database,
            owner_id,
            "participant_qualified",
            f"{invitation['recipient']} qualified in position {position} for Package #{circle['sequence_number']}",
            "circle",
            circle["id"],
        )
        qualified_count = position

    circle_completed = False
    reward_created = False
    if qualified_count == circle["required_participants"]:
        completed_at = utc_now()
        database.execute(
            "UPDATE circles SET status = 'completed', completed_at = ? WHERE id = ?",
            (completed_at, circle["id"]),
        )
        reward = database.execute(
            "SELECT id FROM rewards WHERE circle_id = ?", (circle["id"],)
        ).fetchone()
        if reward is None:
            reward_cursor = database.execute(
                """
                INSERT INTO rewards (user_id, circle_id, status, eligible_at)
                VALUES (?, ?, 'available', ?)
                """,
                (owner_id, circle["id"], completed_at),
            )
            reward_created = True
            record_event(
                database,
                owner_id,
                "reward_eligible",
                f"Reward available for Package #{circle['sequence_number']}",
                "reward",
                reward_cursor.lastrowid,
            )
        record_event(
            database,
            owner_id,
            "circle_completed",
            f"Package #{circle['sequence_number']} completed",
            "circle",
            circle["id"],
        )
        record_transaction(
            database,
            owner_id,
            "Package",
            f"Package #{circle['sequence_number']} completed",
            "Reward Available",
        )
        circle_completed = True

    return {
        "changed": True,
        "qualified": qualified,
        "circle_completed": circle_completed,
        "package_completed": circle_completed,
        "reward_created": reward_created,
        "circle": get_circle_by_id(database, circle["id"]),
        "package": get_circle_by_id(database, circle["id"]),
    }


def get_circle_by_id(database, circle_id):
    circle = database.execute("SELECT * FROM circles WHERE id = ?", (circle_id,)).fetchone()
    if circle is None:
        return None
    participants = database.execute(
        """
        SELECT cp.id, cp.position_number, cp.status, cp.qualified_at,
               i.id AS invitation_id, i.recipient
        FROM circle_participants cp
        JOIN invitations i ON i.id = cp.invitation_id
        WHERE cp.circle_id = ?
        ORDER BY cp.position_number
        """,
        (circle_id,),
    ).fetchall()
    participant_data = [
        {
            **serialize_row(participant),
            "status": as_status(participant["status"]),
            "initials": _initials(participant["recipient"]),
        }
        for participant in participants
    ]
    slots = []
    by_position = {item["position_number"]: item for item in participant_data}
    for position in range(1, circle["required_participants"] + 1):
        slots.append(
            {
                "position": position,
                "filled": position in by_position,
                "participant": by_position.get(position),
            }
        )
    return {
        **serialize_row(circle),
        "status": as_status(circle["status"]),
        "qualified_count": len(participant_data),
        "participants": participant_data,
        "slots": slots,
    }


def get_current_or_latest_circle(database, user_id):
    row = database.execute(
        """
        SELECT id FROM circles
        WHERE user_id = ?
        ORDER BY CASE WHEN status = 'active' THEN 0 ELSE 1 END, sequence_number DESC
        LIMIT 1
        """,
        (user_id,),
    ).fetchone()
    return get_circle_by_id(database, row["id"]) if row else None


def get_circle_history(database, user_id):
    rows = database.execute(
        "SELECT id FROM circles WHERE user_id = ? ORDER BY sequence_number DESC",
        (user_id,),
    ).fetchall()
    return [get_circle_by_id(database, row["id"]) for row in rows]


def get_dashboard(database, user_id):
    user = database.execute(
        "SELECT id, name, email, status, is_admin FROM users WHERE id = ?", (user_id,)
    ).fetchone()
    invitation_count = database.execute(
        "SELECT COUNT(*) AS count FROM invitations WHERE user_id = ?", (user_id,)
    ).fetchone()["count"]
    activation_count = database.execute(
        "SELECT COUNT(*) AS count FROM activations WHERE user_id = ?", (user_id,)
    ).fetchone()["count"]
    available_rewards = database.execute(
        "SELECT COUNT(*) AS count FROM rewards WHERE user_id = ? AND status = 'available'",
        (user_id,),
    ).fetchone()["count"]
    current_circle = get_current_or_latest_circle(database, user_id)
    history_count = database.execute(
        "SELECT COUNT(*) AS count FROM circles WHERE user_id = ? AND status = 'completed'",
        (user_id,),
    ).fetchone()["count"]
    activities = database.execute(
        """
        SELECT id, event_type, description, occurred_at
        FROM audit_events
        WHERE user_id = ?
        ORDER BY occurred_at DESC, id DESC
        LIMIT 6
        """,
        (user_id,),
    ).fetchall()
    circle_status = current_circle["status"] if current_circle else as_status("active")
    reward_status = as_status("available") if available_rewards else {
        "key": "none",
        "label": "Not yet available",
        "tone": "neutral",
    }
    return {
        "member": {**serialize_row(user), "status": as_status(user["status"])},
        "account_status": as_status(user["status"]),
        "circle_status": circle_status,
        "package_status": circle_status,
        "current_circle": current_circle,
        "current_package": current_circle,
        "completed_circle_count": history_count,
        "completed_package_count": history_count,
        "qualifying_participants": {
            "value": current_circle["qualified_count"] if current_circle else 0,
            "target": PACKAGE_SIZE,
            "label": f"{current_circle['qualified_count'] if current_circle else 0} / {PACKAGE_SIZE} Qualified",
        },
        "invitation_count": invitation_count,
        "payment_status": {
            "count": activation_count,
            "label": f"{activation_count} mock activation{'s' if activation_count != 1 else ''}",
            "tone": "green" if activation_count else "neutral",
        },
        "reward_status": reward_status,
        "available_reward_count": available_rewards,
        "recent_activity": [serialize_row(item) for item in activities],
    }


def get_circle(database, user_id):
    current = get_current_or_latest_circle(database, user_id)
    if current is None:
        current = get_circle_by_id(database, ensure_active_circle(database, user_id)["id"])
    return {
        "current": current,
        "history": get_circle_history(database, user_id),
        "qualification_policy": QUALIFICATION_POLICY,
        "target_description": "The first five paid / activated participants fill the five qualifying positions in a package.",
    }


def get_invitations(database, user_id):
    rows = database.execute(
        """
        SELECT i.id, i.recipient, i.status, i.sent_at, i.invitation_message_id,
               CASE WHEN a.id IS NULL THEN 0 ELSE 1 END AS is_activated,
               cp.circle_id, cp.position_number
        FROM invitations i
        LEFT JOIN activations a ON a.invitation_id = i.id
        LEFT JOIN circle_participants cp ON cp.invitation_id = i.id
        WHERE i.user_id = ?
        ORDER BY i.id DESC
        """,
        (user_id,),
    ).fetchall()
    return [
        {
            **serialize_row(row),
            "package_id": row["circle_id"],
            "status_meta": as_status(row["status"]),
            "is_activated": bool(row["is_activated"]),
        }
        for row in rows
    ]


def get_transactions(database, user_id):
    rows = database.execute(
        """
        SELECT id, type, description, status, amount_label, occurred_at
        FROM transactions
        WHERE user_id = ?
        ORDER BY occurred_at DESC, id DESC
        """,
        (user_id,),
    ).fetchall()
    return [
        {**serialize_row(row), "formatted_date": _format_date(row["occurred_at"])}
        for row in rows
    ]


def get_rewards(database, user_id):
    rows = database.execute(
        """
        SELECT r.id, r.status, r.eligible_at, r.redeemed_at,
               c.id AS circle_id, c.sequence_number
        FROM rewards r
        JOIN circles c ON c.id = r.circle_id
        WHERE r.user_id = ?
        ORDER BY r.id DESC
        """,
        (user_id,),
    ).fetchall()
    return [
        {
            **serialize_row(row),
            "package_id": row["circle_id"],
            "status_meta": as_status(row["status"]),
        }
        for row in rows
    ]


def get_admin_overview(database):
    users = database.execute(
        """
        SELECT u.id, u.name, u.email, u.status, u.is_admin,
               u.phone_verified,
               COUNT(DISTINCT c.id) AS circle_count,
               COUNT(DISTINCT CASE WHEN c.status = 'completed' THEN c.id END) AS completed_count,
               COUNT(DISTINCT r.id) AS reward_count
        FROM users u
        LEFT JOIN circles c ON c.user_id = u.id
        LEFT JOIN rewards r ON r.user_id = u.id
        GROUP BY u.id
        ORDER BY u.id
        """
    ).fetchall()
    invitations = database.execute(
        """
        SELECT i.id, i.recipient, i.status, i.sent_at, u.name AS owner_name,
               CASE WHEN a.id IS NULL THEN 0 ELSE 1 END AS is_activated
        FROM invitations i
        JOIN users u ON u.id = i.user_id
        LEFT JOIN activations a ON a.invitation_id = i.id
        ORDER BY i.id DESC
        """
    ).fetchall()
    circles = database.execute(
        """
        SELECT c.id, c.sequence_number, c.status, c.created_at, c.completed_at,
               u.name AS owner_name,
               COUNT(cp.id) AS qualified_count
        FROM circles c
        JOIN users u ON u.id = c.user_id
        LEFT JOIN circle_participants cp ON cp.circle_id = c.id
        GROUP BY c.id
        ORDER BY c.id DESC
        """
    ).fetchall()
    rewards = database.execute(
        """
        SELECT r.id, r.status, r.eligible_at, u.name AS owner_name, c.sequence_number
        FROM rewards r
        JOIN users u ON u.id = r.user_id
        JOIN circles c ON c.id = r.circle_id
        ORDER BY r.id DESC
        """
    ).fetchall()
    return {
        "users": [
            {
                **serialize_row(row),
                "package_count": row["circle_count"],
            }
            for row in users
        ],
        "invitations": [
            {**serialize_row(row), "is_activated": bool(row["is_activated"])}
            for row in invitations
        ],
        "circles": [serialize_row(row) for row in circles],
        "packages": [serialize_row(row) for row in circles],
        "rewards": [serialize_row(row) for row in rewards],
        "counts": {
            "users": len(users),
            "invitations": len(invitations),
            "circles": len(circles),
            "packages": len(circles),
            "completed": sum(1 for row in circles if row["status"] == "completed"),
            "rewards": len(rewards),
        },
    }


def get_profile(database, user_id):
    row = database.execute(
        """
        SELECT id, name, email, phone, country_calling_code, normalized_phone,
               phone_verified, phone_verified_at, status, joined_at, is_admin
        FROM users WHERE id = ?
        """,
        (user_id,),
    ).fetchone()
    profile = serialize_row(row)
    profile["status"] = as_status(row["status"])
    profile["is_admin"] = bool(row["is_admin"])
    profile["phone_verified"] = bool(row["phone_verified"])
    return profile


def update_profile(database, user_id, name, phone):
    if name:
        database.execute(
            "UPDATE users SET name = ? WHERE id = ?",
            (name, user_id),
        )


def get_settings(database, user_id):
    row = database.execute(
        """
        SELECT email_notifications, invitation_reminders, preferred_language
        FROM settings WHERE user_id = ?
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


def _initials(value):
    words = [word for word in value.replace("@", " ").split() if word]
    return "".join(word[0].upper() for word in words[:2]) or "KP"


def _format_date(value):
    try:
        return datetime.fromisoformat(value).strftime("%b %-d, %Y")
    except (TypeError, ValueError):
        return value


# Canonical Package application API. These wrappers intentionally delegate to
# the existing circle-backed implementation so historical SQLite data remains
# in one source of truth.
def ensure_active_package(database, user_id):
    return ensure_active_circle(database, user_id)


def _package_record(record):
    if record is None:
        return None
    package = dict(record)
    package["package_id"] = package["id"]
    package["package_status"] = package["status"]
    package["package_participants"] = package["participants"]
    return package


def start_new_package(database, user_id):
    result = start_new_circle(database, user_id)
    if result.get("circle") is not None:
        result["package"] = _package_record(result["circle"])
    return result


def get_package(database, user_id):
    result = get_circle(database, user_id)
    result["current_package"] = _package_record(result["current"])
    result["package_history"] = [
        _package_record(package) for package in result["history"]
    ]
    return result


def get_package_history(database, user_id):
    return [_package_record(package) for package in get_circle_history(database, user_id)]
