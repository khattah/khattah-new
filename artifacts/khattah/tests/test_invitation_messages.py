import os
import tempfile
import unittest

from werkzeug.security import generate_password_hash

from app import app, get_db, init_db
from services.invitation_messages import (
    CHANNELS, create_message, get_message_audit, make_invite_token,
    set_message_state, update_message, available_messages, read_invite_token,
)
from services.khattah import create_invitation, ensure_active_package


class InvitationMessageTests(unittest.TestCase):
    def setUp(self):
        handle, self.path = tempfile.mkstemp(suffix=".sqlite3")
        os.close(handle)
        app.config.update(TESTING=True, DATABASE=self.path, SEED_DEMO_DATA=False,
                          SECRET_KEY="invitation-message-tests")
        self.client = app.test_client()
        with app.app_context():
            init_db()
            db = get_db()
            admin = db.execute(
                "INSERT INTO users(name,email,password_hash,status,joined_at,is_admin) VALUES(?,?,?,?,?,1)",
                ("Admin", "admin@messages.test", generate_password_hash("Admin1234!"), "activated", "2024-01-01"),
            )
            member = db.execute(
                "INSERT INTO users(name,email,password_hash,status,joined_at,is_admin) VALUES(?,?,?,?,?,0)",
                ("Member", "member@messages.test", generate_password_hash("Member1234!"), "registered", "2024-01-01"),
            )
            self.admin_id, self.member_id = admin.lastrowid, member.lastrowid
            db.executemany("INSERT INTO settings(user_id) VALUES (?)", [(self.admin_id,), (self.member_id,)])
            ensure_active_package(db, self.member_id)
            db.commit()

    def tearDown(self):
        os.remove(self.path)

    def login(self, user_id):
        with self.client.session_transaction() as session:
            session.clear()
            session["user_id"] = user_id

    def csrf(self, path="/"):
        self.client.get(path)
        with self.client.session_transaction() as session:
            return session["csrf_token"]

    def message(self, channel="general", language="en", body="Join {inviter_name}: {invite_link}"):
        with app.app_context():
            row = create_message(get_db(), self.admin_id, {
                "campaign_name": "Test", "channel": channel, "language": language,
                "subject": "Subject", "body": body,
            })
            get_db().commit()
            return row["id"]

    def approve_activate(self, message_id):
        with app.app_context():
            set_message_state(get_db(), message_id, self.admin_id, "approve")
            set_message_state(get_db(), message_id, self.admin_id, "activate")
            get_db().commit()

    def test_four_state_combinations_and_archived_filter(self):
        ids = [self.message() for _ in range(4)]
        with app.app_context():
            set_message_state(get_db(), ids[1], self.admin_id, "approve")
            set_message_state(get_db(), ids[2], self.admin_id, "approve")
            set_message_state(get_db(), ids[2], self.admin_id, "activate")
            set_message_state(get_db(), ids[3], self.admin_id, "archive")
            self.assertEqual({r["id"] for r in available_messages(get_db())}, {ids[2]})
            self.assertEqual(len(get_db().execute("SELECT * FROM invitation_messages").fetchall()), 4)

    def test_all_channels_and_languages(self):
        for channel in CHANNELS:
            for language in ("en", "ar"):
                self.assertIsNotNone(self.message(channel, language))

    def test_user_rejects_missing_and_unavailable_messages(self):
        self.login(self.member_id)
        token = self.csrf("/invitations")
        self.assertEqual(self.client.post("/invitations", data={"recipient": "x", "csrf_token": token}).status_code, 302)
        self.assertEqual(self.client.post("/api/v1/invitations", json={"recipient": "x"}, headers={"X-CSRF-Token": token}).status_code, 400)
        mid = self.message()
        for state in ("draft", "inactive", "unapproved_active", "archived"):
            with app.app_context():
                db = get_db()
                if state == "unapproved_active":
                    db.execute("UPDATE invitation_messages SET is_active=1 WHERE id=?", (mid,))
                elif state == "archived":
                    db.execute("UPDATE invitation_messages SET is_archived=1 WHERE id=?", (mid,))
                db.commit()
            response = self.client.post("/invitations", data={"recipient": state, "invitation_message_id": mid, "csrf_token": self.csrf("/invitations")})
            self.assertEqual(response.status_code, 302)
            with app.app_context():
                self.assertEqual(get_db().execute("SELECT COUNT(*) c FROM invitations WHERE recipient=?", (state,)).fetchone()["c"], 0)

    def test_non_admin_and_csrf_are_forbidden(self):
        self.login(self.member_id)
        self.assertNotEqual(self.client.get("/admin/invitation-messages").status_code, 200)
        self.assertEqual(self.client.post("/api/v1/admin/invitation-messages", json={}, headers={"X-CSRF-Token": self.csrf("/invitations")}).status_code, 403)
        self.assertEqual(self.client.post("/admin/invitation-messages", data={}).status_code, 400)

    def test_edit_resets_state_archive_and_audit_actor(self):
        mid = self.message()
        self.approve_activate(mid)
        with app.app_context():
            update_message(get_db(), mid, self.admin_id, {"campaign_name": "Test", "channel": "sms", "language": "ar", "subject": "Changed", "body": "Changed {invite_link}"})
            row = get_db().execute("SELECT is_approved,is_active FROM invitation_messages WHERE id=?", (mid,)).fetchone()
            self.assertEqual((row["is_approved"], row["is_active"]), (0, 0))
            set_message_state(get_db(), mid, self.admin_id, "archive")
            self.assertIsNotNone(get_db().execute("SELECT id FROM invitation_messages WHERE id=?", (mid,)).fetchone())
            audits = get_message_audit(get_db(), mid)
            self.assertTrue(all(a["actor_name"] == "Admin" and a["action"] and a["occurred_at"] for a in audits))

    def test_placeholder_and_signed_link_security(self):
        with self.assertRaises(ValueError):
            self.message(body="Bad {password}")
        with app.app_context():
            invitation = create_invitation(get_db(), self.member_id, "recipient")
            get_db().commit()
            token = make_invite_token(app.config["SECRET_KEY"], invitation["id"], self.member_id)
        self.assertEqual(self.client.get("/invite/" + token).status_code, 200)
        self.assertEqual(self.client.get("/invite/" + token + "tampered").status_code, 404)
        self.assertIsNone(read_invite_token(app.config["SECRET_KEY"], token, max_age=-1))

    def test_archived_is_terminal_and_cross_owner_payload_does_not_resolve(self):
        mid = self.message()
        with app.app_context():
            set_message_state(get_db(), mid, self.admin_id, "archive")
            for action in ("approve", "activate", "deactivate"):
                with self.assertRaises(ValueError):
                    set_message_state(get_db(), mid, self.admin_id, action)
            with self.assertRaises(ValueError):
                update_message(get_db(), mid, self.admin_id, {"campaign_name": "x", "channel": "sms", "language": "en", "subject": "x", "body": "x"})
            invitation = create_invitation(get_db(), self.member_id, "owner")
            token = make_invite_token(app.config["SECRET_KEY"], invitation["id"], self.admin_id)
            get_db().commit()
        self.assertEqual(self.client.get("/invite/" + token).status_code, 404)

    def test_public_get_does_not_mutate_business_records_and_screens_render(self):
        self.login(self.admin_id)
        self.assertEqual(self.client.get("/admin/invitation-messages").status_code, 200)
        mid = self.message("whatsapp", "ar")
        self.approve_activate(mid)
        self.login(self.member_id)
        self.assertEqual(self.client.get("/invitations").status_code, 200)
        with app.app_context():
            invitation = create_invitation(get_db(), self.member_id, "r", mid)
            get_db().commit()
            token = make_invite_token(app.config["SECRET_KEY"], invitation["id"], self.member_id)
            before = [get_db().execute(f"SELECT COUNT(*) c FROM {table}").fetchone()["c"] for table in ("invitations", "activations", "circle_participants")]
        screen = self.client.get("/invitations").get_data(as_text=True)
        self.assertIn("Copy message for Messenger", screen)
        self.assertIn('href="https://www.messenger.com/"', screen)
        self.assertNotIn("app_id", screen)
        public = self.client.get("/invite/" + token).get_data(as_text=True)
        self.assertIn('name="robots" content="noindex,nofollow"', public)
        self.assertIn('property="og:title"', public)
        self.assertIn('property="og:description"', public)
        self.assertIn('property="og:url"', public)
        with app.app_context():
            after = [get_db().execute(f"SELECT COUNT(*) c FROM {table}").fetchone()["c"] for table in ("invitations", "activations", "circle_participants")]
            self.assertEqual(before, after)

    def test_development_seed_is_idempotent_and_complete(self):
        app.config["SEED_DEMO_DATA"] = True
        with app.app_context():
            init_db()
            init_db()
            rows = get_db().execute("SELECT DISTINCT channel,language FROM invitation_messages").fetchall()
            self.assertEqual(len(rows), 16)