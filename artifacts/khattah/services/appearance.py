"""Presentation-only appearance settings for the KHATTAH application."""
import re

TEMPLATE_KEYS = ("classic", "modern", "minimal", "premium", "mobile")
COLOR_FIELDS = (
    "primary", "secondary", "background", "header", "navigation", "button",
    "card", "text", "link", "border", "status_invited", "status_paid",
    "status_reward", "status_completed",
)
ICON_ALLOWLIST = ("package", "star", "shield", "spark", "diamond")
HEX_RE = re.compile(r"^#[0-9A-Fa-f]{6}$")

DEFAULT_PALETTES = {
    "classic": {"primary": "#102725", "secondary": "#173633", "background": "#F5F3ED", "header": "#102725", "navigation": "#102725", "button": "#F07A63", "card": "#FFFEFA", "text": "#102725", "link": "#DC614B", "border": "#DEDDD6", "status_invited": "#E8B833", "status_paid": "#39A86B", "status_reward": "#3F7EC9", "status_completed": "#DC554F"},
    "modern": {"primary": "#24104F", "secondary": "#5E35B1", "background": "#F7F5FC", "header": "#24104F", "navigation": "#24104F", "button": "#FF6B6B", "card": "#FFFFFF", "text": "#211A2E", "link": "#5E35B1", "border": "#DDD6F2", "status_invited": "#E9B949", "status_paid": "#28B485", "status_reward": "#4F7CFF", "status_completed": "#D64550"},
    "minimal": {"primary": "#1E293B", "secondary": "#475569", "background": "#F8FAFC", "header": "#FFFFFF", "navigation": "#FFFFFF", "button": "#0F766E", "card": "#FFFFFF", "text": "#1E293B", "link": "#0F766E", "border": "#CBD5E1", "status_invited": "#CA8A04", "status_paid": "#15803D", "status_reward": "#2563EB", "status_completed": "#B91C1C"},
    "premium": {"primary": "#211A16", "secondary": "#8A6A45", "background": "#F4EFE7", "header": "#211A16", "navigation": "#211A16", "button": "#B7793E", "card": "#FFFDF9", "text": "#211A16", "link": "#8A5A2B", "border": "#D8C6AA", "status_invited": "#B78B24", "status_paid": "#3B7D5A", "status_reward": "#4A6FA5", "status_completed": "#A34545"},
    "mobile": {"primary": "#092F3D", "secondary": "#0B7285", "background": "#EAF6F7", "header": "#092F3D", "navigation": "#092F3D", "button": "#F08A5D", "card": "#FFFFFF", "text": "#082F49", "link": "#0B7285", "border": "#B9DDE0", "status_invited": "#C38D18", "status_paid": "#198754", "status_reward": "#3973B8", "status_completed": "#C74B50"},
}


def validate_template(key):
    if key not in TEMPLATE_KEYS:
        raise ValueError("invalid appearance template")
    return key


def validate_colors(values):
    result = {}
    for field in COLOR_FIELDS:
        value = str(values.get(field, "")).strip()
        if not HEX_RE.fullmatch(value):
            raise ValueError(f"invalid color for {field}")
        result[field] = value.upper()
    return result


def validate_package(values):
    sequence = int(values.get("sequence_number", 0))
    if sequence <= 0:
        raise ValueError("sequence number must be positive")
    if values.get("icon", "package") not in ICON_ALLOWLIST:
        raise ValueError("invalid package icon")
    def as_bool(value, default=False):
        if value is None:
            return int(default)
        if isinstance(value, bool):
            return int(value)
        return int(str(value).strip().lower() in {"1", "true", "yes", "on"})
    return {
        "sequence_number": sequence,
        "name_en": str(values.get("name_en", "")).strip()[:80],
        "name_ar": str(values.get("name_ar", "")).strip()[:80],
        "description_en": str(values.get("description_en", "")).strip()[:240],
        "description_ar": str(values.get("description_ar", "")).strip()[:240],
        "icon": values.get("icon", "package"),
        "display_order": max(0, int(values.get("display_order", sequence))),
        "is_visible": as_bool(values.get("is_visible"), False),
        "is_active": as_bool(values.get("is_active"), False),
    }


def get_settings(database):
    row = database.execute("SELECT * FROM appearance_settings WHERE id=1").fetchone()
    return dict(row)


def list_colors(database):
    return [_normalize_colors(row) for row in database.execute(
        "SELECT * FROM template_color_settings ORDER BY CASE template_key "
        "WHEN 'classic' THEN 1 WHEN 'modern' THEN 2 WHEN 'minimal' THEN 3 "
        "WHEN 'premium' THEN 4 ELSE 5 END"
    )]


def get_colors(database, key):
    validate_template(key)
    row = database.execute("SELECT * FROM template_color_settings WHERE template_key=?", (key,)).fetchone()
    return _normalize_colors(row)


def _normalize_colors(row):
    raw = dict(row)
    result = {"template_key": raw["template_key"], "updated_at": raw["updated_at"]}
    for field in COLOR_FIELDS:
        result[field] = raw[f"{field}_color"] if not field.startswith("status_") else raw[field]
    return result


def get_package_display(database, sequence, language="en"):
    row = database.execute("SELECT * FROM package_display_settings WHERE sequence_number=?", (sequence,)).fetchone()
    if row is None:
        return {"sequence_number": sequence, "name": f"Package #{sequence}" if language != "ar" else f"الباقة #{sequence}", "description": "", "icon": "package", "is_visible": 1, "is_active": 1}
    row = dict(row)
    fallback = f"الباقة #{sequence}" if language == "ar" else f"Package #{sequence}"
    if not row["is_visible"] or not row["is_active"]:
        row["name"], row["description"], row["icon"] = fallback, "", "package"
    else:
        row["name"] = row["name_ar" if language == "ar" else "name_en"] or fallback
        row["description"] = row["description_ar" if language == "ar" else "description_en"]
    return row


def list_package_display(database):
    return [dict(row) for row in database.execute("SELECT * FROM package_display_settings ORDER BY display_order, sequence_number")]


def audit(database, category, setting_key, previous, new, actor):
    database.execute("INSERT INTO appearance_audit(category, setting_key, previous_value, new_value, actor_user_id, occurred_at) VALUES(?,?,?,?,?,datetime('now'))", (category, setting_key, previous, new, actor))


def activate(database, kind, key, actor):
    validate_template(key)
    column = "active_frontend_template" if kind == "frontend" else "active_admin_template" if kind == "admin" else None
    if column is None:
        raise ValueError("invalid appearance target")
    old = database.execute(f"SELECT {column} FROM appearance_settings WHERE id=1").fetchone()[column]
    database.execute(f"UPDATE appearance_settings SET {column}=?, updated_at=datetime('now') WHERE id=1", (key,))
    audit(database, "activation", column, old, key, actor)


def save_colors(database, key, values, actor):
    validate_template(key)
    colors = validate_colors(values)
    old = get_colors(database, key)
    column_map = {field: f"{field}_color" for field in COLOR_FIELDS
                  if not field.startswith("status_")}
    column_map.update({field: field for field in COLOR_FIELDS if field.startswith("status_")})
    assignments = ", ".join(f"{column_map[field]}=?" for field in COLOR_FIELDS)
    database.execute(f"UPDATE template_color_settings SET {assignments}, updated_at=datetime('now') WHERE template_key=?", (*[colors[f] for f in COLOR_FIELDS], key))
    old_values = {f: old[f] for f in COLOR_FIELDS}
    audit(database, "colors", key, str(old_values), str(colors), actor)


def reset_colors(database, key, actor):
    save_colors(database, key, DEFAULT_PALETTES[key], actor)


def save_package(database, values, actor):
    item = validate_package(values)
    old = database.execute("SELECT * FROM package_display_settings WHERE sequence_number=?", (item["sequence_number"],)).fetchone()
    database.execute("""INSERT INTO package_display_settings
        (sequence_number,name_en,name_ar,description_en,description_ar,icon,display_order,is_visible,is_active,updated_at)
        VALUES (:sequence_number,:name_en,:name_ar,:description_en,:description_ar,:icon,:display_order,:is_visible,:is_active,datetime('now'))
        ON CONFLICT(sequence_number) DO UPDATE SET name_en=excluded.name_en,name_ar=excluded.name_ar,
        description_en=excluded.description_en,description_ar=excluded.description_ar,icon=excluded.icon,
        display_order=excluded.display_order,is_visible=excluded.is_visible,is_active=excluded.is_active,updated_at=datetime('now')""", item)
    audit(database, "package_display", str(item["sequence_number"]), str(dict(old) if old else None), str(item), actor)


def audit_rows(database):
    return [dict(row) for row in database.execute("""SELECT a.*, u.name AS actor_name FROM appearance_audit a
        JOIN users u ON u.id=a.actor_user_id ORDER BY a.id DESC LIMIT 100""")]