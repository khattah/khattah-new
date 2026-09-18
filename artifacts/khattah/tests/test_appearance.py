import os
import tempfile
import unittest

from werkzeug.security import generate_password_hash

from app import app, get_db, init_db
from services.appearance import (
    COLOR_FIELDS, DEFAULT_PALETTES, TEMPLATE_KEYS, activate, get_colors,
    get_package_display, list_package_display, reset_colors, save_colors,
    save_package,
)


class AppearanceTests(unittest.TestCase):
    def setUp(self):
        handle, self.path = tempfile.mkstemp(suffix=".sqlite3")
        os.close(handle)
        app.config.update(TESTING=True, DATABASE=self.path, SECRET_KEY="appearance-test",
                          SEED_DEMO_DATA=False)
        self.client = app.test_client()
        with app.app_context():
            init_db()
            db = get_db()
            db.execute("INSERT INTO users(name,email,password_hash,status,joined_at,is_admin) VALUES(?,?,?,?,?,1)",
                       ("Admin", "appearance-admin@test", generate_password_hash("Admin1234!"), "activated", "2026-01-01"))
            db.execute("INSERT INTO users(name,email,password_hash,status,joined_at,is_admin) VALUES(?,?,?,?,?,0)",
                       ("Member", "appearance-member@test", generate_password_hash("Member1234!"), "activated", "2026-01-01"))
            db.execute("INSERT INTO settings(user_id) SELECT id FROM users WHERE email IN (?,?)",
                       ("appearance-admin@test", "appearance-member@test"))
            db.commit()

    def tearDown(self):
        try:
            os.unlink(self.path)
        except FileNotFoundError:
            pass

    def login(self, email, password):
        page = self.client.get("/login")
        with app.test_request_context():
            pass
        with self.client.session_transaction() as session:
            token = session["csrf_token"]
        return self.client.post("/login", data={"email": email, "password": password,
                                                "csrf_token": token}, follow_redirects=True)

    def test_defaults_are_exactly_five_and_migration_is_idempotent(self):
        with app.app_context():
            db = get_db()
            self.assertEqual(tuple(r[0] for r in db.execute("SELECT template_key FROM template_color_settings ORDER BY template_key")), tuple(sorted(TEMPLATE_KEYS)))
            self.assertEqual(db.execute("SELECT COUNT(*) FROM package_display_settings").fetchone()[0], 5)
            init_db()
            self.assertEqual(db.execute("SELECT COUNT(*) FROM template_color_settings").fetchone()[0], 5)

    def test_palette_validation_reset_and_independent_activation(self):
        with app.app_context():
            db = get_db()
            actor = db.execute("SELECT id FROM users WHERE is_admin=1").fetchone()[0]
            changed = dict(DEFAULT_PALETTES["modern"]); changed["primary"] = "#ABCDEF"
            save_colors(db, "modern", changed, actor)
            self.assertEqual(get_colors(db, "modern")["primary"], "#ABCDEF")
            self.assertNotEqual(get_colors(db, "classic")["primary"], "#ABCDEF")
            with self.assertRaises(ValueError):
                save_colors(db, "modern", {**changed, "primary": "red"}, actor)
            with self.assertRaises(ValueError):
                save_colors(db, "not-a-theme", changed, actor)
            with self.assertRaises(ValueError):
                save_package(db, {"sequence_number": 1, "icon": "script"}, actor)
            reset_colors(db, "modern", actor)
            self.assertEqual(get_colors(db, "modern")["primary"], DEFAULT_PALETTES["modern"]["primary"])
            activate(db, "frontend", "modern", actor)
            activate(db, "admin", "premium", actor)
            row = db.execute("SELECT * FROM appearance_settings WHERE id=1").fetchone()
            self.assertEqual(row["active_frontend_template"], "modern")
            self.assertEqual(row["active_admin_template"], "premium")

    def test_scope_preview_and_package_metadata(self):
        self.login("appearance-admin@test", "Admin1234!")
        with app.app_context():
            db = get_db()
            actor = db.execute("SELECT id FROM users WHERE is_admin=1").fetchone()[0]
            save_package(db, {"sequence_number": 1, "name_en": "Welcome", "name_ar": "مرحبا",
                              "description_en": "First", "description_ar": "الأولى",
                              "display_order": 9, "is_visible": 1, "is_active": 1}, actor)
            item = get_package_display(db, 1, "ar")
            self.assertEqual(item["name"], "مرحبا")
            self.assertEqual(item["display_order"], 9)
            self.assertTrue(item["is_visible"])
            self.assertEqual(get_package_display(db, 99, "ar")["name"], "الباقة #99")
            save_package(db, {"sequence_number": 1, "name_en": "Hidden",
                              "name_ar": "مخفي", "icon": "package",
                              "display_order": 1}, actor)
            hidden = get_package_display(db, 1, "en")
            self.assertFalse(hidden["is_visible"])
            self.assertFalse(hidden["is_active"])
            self.assertEqual(hidden["name"], "Package #1")
        response = self.client.get("/dashboard?preview=modern")
        self.assertIn(b'theme-modern', response.data)
        response = self.client.get("/dashboard?preview=modern&preview_scope=frontend")
        self.assertIn(b'theme-modern', response.data)
        self.assertIn(b'--theme-primary: #24104F;', response.data)
        self.assertNotIn(b'--theme-primary: ;', response.data)
        response = self.client.get("/admin?preview=minimal")
        self.assertIn(b'theme-minimal', response.data)
        with app.app_context():
            row = get_db().execute("SELECT active_frontend_template,active_admin_template FROM appearance_settings").fetchone()
            self.assertEqual(row["active_frontend_template"], "classic")
            self.assertEqual(row["active_admin_template"], "classic")

    def test_non_admin_cannot_change_appearance(self):
        self.login("appearance-member@test", "Member1234!")
        response = self.client.get("/admin/appearance", follow_redirects=False)
        self.assertIn(response.status_code, (302, 403))
        with self.client.session_transaction() as session:
            token = session["csrf_token"]
        response = self.client.patch("/api/v1/admin/appearance",
                                     headers={"X-CSRF-Token": token},
                                     json={"action": "activate", "kind": "frontend", "template": "modern"})
        self.assertEqual(response.status_code, 403)


if __name__ == "__main__":
    unittest.main()