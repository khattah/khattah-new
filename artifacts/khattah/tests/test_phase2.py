import os
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

from werkzeug.security import generate_password_hash

from app import app, create_invitation, ensure_active_package, get_db, init_db, migrate_db
from services.khattah import save_package_configuration
from services.invitation_messages import create_message, make_invite_token, set_message_state
from services.i18n import translate
from services.phone_verification import (
    DuplicatePhoneError,
    InvalidPhoneError,
    PhoneVerificationError,
    VerificationRateLimitError,
    mock_sms_provider,
    request_verification,
    verify_code,
)


class PhaseTwoTests(unittest.TestCase):
    def setUp(self):
        handle, self.database_path = tempfile.mkstemp(suffix=".sqlite3")
        os.close(handle)
        app.config.update(
            TESTING=True,
            DATABASE=self.database_path,
            SEED_DEMO_DATA=False,
            SECRET_KEY="phase-two-tests",
            PHONE_API_REQUESTS_PER_HOUR=10,
        )
        self.client = app.test_client()
        mock_sms_provider.clear()
        with app.app_context():
            init_db()
            database = get_db()
            admin = database.execute(
                """
                INSERT INTO users
                    (name, email, password_hash, status, joined_at, is_admin)
                VALUES ('Test Admin', 'admin@test.local', ?, 'activated', '2026-09-17', 1)
                """,
                (generate_password_hash("Admin1234!"),),
            )
            member = database.execute(
                """
                INSERT INTO users
                    (name, email, password_hash, status, joined_at, is_admin)
                VALUES ('Test Member', 'member@test.local', ?, 'registered', '2026-09-17', 0)
                """,
                (generate_password_hash("Member1234!"),),
            )
            self.admin_id = admin.lastrowid
            self.member_id = member.lastrowid
            database.executemany(
                "INSERT INTO settings (user_id) VALUES (?)",
                [(self.admin_id,), (self.member_id,)],
            )
            ensure_active_package(database, self.member_id)
            message = create_message(database, self.admin_id, {
                "campaign_name": "Test catalogue", "channel": "general",
                "language": "en", "subject": "Invitation",
                "body": "Join {inviter_name}: {invite_link}",
            })
            set_message_state(database, message["id"], self.admin_id, "approve")
            set_message_state(database, message["id"], self.admin_id, "activate")
            self.invitation_message_id = message["id"]
            database.commit()

    def tearDown(self):
        os.remove(self.database_path)

    def login_as(self, user_id):
        with self.client.session_transaction() as session:
            session.clear()
            session["user_id"] = user_id

    def csrf_token(self, path="/"):
        self.client.get(path)
        with self.client.session_transaction() as session:
            return session["csrf_token"]

    def invitation_ids(self):
        with app.app_context():
            return [
                row["id"]
                for row in get_db().execute(
                    "SELECT id FROM invitations WHERE user_id = ? ORDER BY id",
                    (self.member_id,),
                )
            ]

    def create_invitations(self, start, count):
        self.login_as(self.member_id)
        for index in range(start, start + count):
            response = self.client.post(
                "/invitations",
                data={
                    "recipient": f"Participant {index}",
                    "invitation_message_id": self.invitation_message_id,
                    "csrf_token": self.csrf_token("/invitations"),
                },
            )
            self.assertEqual(response.status_code, 302)

    def activate(self, invitation_ids):
        self.login_as(self.admin_id)
        for invitation_id in invitation_ids:
            response = self.client.post(
                f"/admin/invitations/{invitation_id}/activate",
                data={"csrf_token": self.csrf_token("/admin")},
            )
            self.assertEqual(response.status_code, 302)

    def test_registration_and_login(self):
        response = self.client.post(
            "/register",
            data={
                "name": "New Member",
                "email": "new.member@test.local",
                "password": "StrongPass123!",
                "country_code": "+1",
                "mobile_number": "306 555 0199",
                "csrf_token": self.csrf_token("/register"),
            },
        )
        self.assertEqual(response.status_code, 200)
        with self.client.session_transaction() as session:
            challenge_token = session["phone_challenge_token"]
        code = mock_sms_provider.code_for_testing(challenge_token)
        self.assertIsNotNone(code)

        response = self.client.post(
            "/register/verify",
            data={
                "verification_code": code,
                "csrf_token": self.csrf_token("/register"),
            },
        )
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.location, "/dashboard")
        with app.app_context():
            user = get_db().execute(
                """
                SELECT normalized_phone, country_calling_code,
                       phone_verified, phone_verified_at
                FROM users WHERE email = 'new.member@test.local'
                """
            ).fetchone()
            self.assertEqual(user["normalized_phone"], "+13065550199")
            self.assertEqual(user["country_calling_code"], "+1")
            self.assertEqual(user["phone_verified"], 1)
            self.assertIsNotNone(user["phone_verified_at"])

        self.client.get("/logout")
        response = self.client.post(
            "/login",
            data={
                "email": "new.member@test.local",
                "password": "StrongPass123!",
                "csrf_token": self.csrf_token("/login"),
            },
        )
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.location, "/dashboard")

    def test_login_page_redirects_and_sidebar_account_labels(self):
        logged_out = self.client.get("/login")
        self.assertEqual(logged_out.status_code, 200)
        self.assertIn('name="password"', logged_out.get_data(as_text=True))

        self.login_as(self.member_id)
        member_redirect = self.client.get("/login")
        self.assertEqual(member_redirect.status_code, 302)
        self.assertEqual(member_redirect.location, "/dashboard")
        member_page = self.client.get("/dashboard").get_data(as_text=True)
        self.assertIn("Member account", member_page)

        self.login_as(self.admin_id)
        admin_redirect = self.client.get("/login")
        self.assertEqual(admin_redirect.status_code, 302)
        self.assertEqual(admin_redirect.location, "/admin")
        admin_page = self.client.get("/admin").get_data(as_text=True)
        self.assertIn("Administrator account", admin_page)

    def test_paid_invitation_links_to_registration_without_duplicate_identity(self):
        with app.app_context():
            database = get_db()
            invitation = create_invitation(
                database,
                self.member_id,
                "omer.ibisolar@gmail.com",
                self.invitation_message_id,
            )
            from services.khattah import activate_invitation
            activate_invitation(database, invitation["id"], self.admin_id)
            token = make_invite_token(
                app.config["SECRET_KEY"], invitation["id"], self.member_id
            )
            database.commit()

        claim_page = self.client.get(f"/invite/{token}")
        self.assertEqual(claim_page.status_code, 200)
        self.assertIn("Establish member account", claim_page.get_data(as_text=True))
        response = self.client.post(
            "/register",
            data={
                "name": "Omer Ibisolar",
                "email": "omer.ibisolar@gmail.com",
                "password": "OmerSecure123!",
                "country_code": "+1",
                "mobile_number": "306 555 0177",
                "csrf_token": self.csrf_token("/register"),
            },
        )
        self.assertEqual(response.status_code, 200)
        with self.client.session_transaction() as session:
            challenge_token = session["phone_challenge_token"]
        code = mock_sms_provider.code_for_testing(challenge_token)
        verified = self.client.post(
            "/register/verify",
            data={
                "verification_code": code,
                "csrf_token": self.csrf_token("/register"),
            },
        )
        self.assertEqual(verified.status_code, 302)
        self.assertEqual(verified.location, "/dashboard")

        with app.app_context():
            database = get_db()
            users = database.execute(
                "SELECT id, status FROM users WHERE lower(email) = lower(?)",
                ("omer.ibisolar@gmail.com",),
            ).fetchall()
            self.assertEqual(len(users), 1)
            self.assertEqual(users[0]["status"], "activated")
            linked = database.execute(
                "SELECT participant_user_id, status FROM invitations WHERE recipient = ?",
                ("omer.ibisolar@gmail.com",),
            ).fetchone()
            self.assertEqual(linked["participant_user_id"], users[0]["id"])
            self.assertEqual(linked["status"], "paid")
            own_package = database.execute(
                "SELECT required_participants FROM circles WHERE user_id = ?",
                (users[0]["id"],),
            ).fetchone()
            self.assertIsNotNone(own_package)

    def test_paid_invitation_cannot_be_claimed_without_signed_link(self):
        email = "unclaimed-paid@test.local"
        with app.app_context():
            database = get_db()
            invitation = create_invitation(
                database, self.member_id, email, self.invitation_message_id
            )
            from services.khattah import activate_invitation
            activate_invitation(database, invitation["id"], self.admin_id)
            database.commit()

        response = self.client.post(
            "/register",
            data={
                "name": "Unclaimed Paid",
                "email": email,
                "password": "StrongPass123!",
                "country_code": "+1",
                "mobile_number": "3065550166",
                "csrf_token": self.csrf_token("/register"),
            },
        )
        self.assertEqual(response.status_code, 200)
        with self.client.session_transaction() as session:
            code = mock_sms_provider.code_for_testing(session["phone_challenge_token"])
        verified = self.client.post(
            "/register/verify",
            data={
                "verification_code": code,
                "csrf_token": self.csrf_token("/register"),
            },
        )
        self.assertEqual(verified.status_code, 302)
        dashboard = self.client.get(verified.location)
        self.assertEqual(dashboard.status_code, 200)
        with app.app_context():
            database = get_db()
            user = database.execute(
                "SELECT id, status FROM users WHERE email = ?", (email,)
            ).fetchone()
            linked = database.execute(
                "SELECT participant_user_id FROM invitations WHERE id = ?",
                (invitation["id"],),
            ).fetchone()
            self.assertEqual(user["status"], "registered")
            self.assertIsNone(linked["participant_user_id"])

    def test_migration_reconciles_existing_linked_paid_member(self):
        with app.app_context():
            database = get_db()
            participant = database.execute(
                """
                INSERT INTO users(name,email,password_hash,status,joined_at,is_admin)
                VALUES('Existing Paid','existing-paid@test.local',?,'registered','2026-09-18',0)
                """,
                (generate_password_hash("Existing123!"),),
            )
            participant_id = participant.lastrowid
            database.execute("INSERT INTO settings(user_id) VALUES(?)", (participant_id,))
            invitation = create_invitation(
                database,
                self.member_id,
                "existing-paid@test.local",
                self.invitation_message_id,
            )
            from services.khattah import activate_invitation
            activate_invitation(database, invitation["id"], self.admin_id)
            database.execute(
                "UPDATE users SET status='registered' WHERE id=?", (participant_id,)
            )
            database.execute("DELETE FROM schema_migrations WHERE version=206")
            database.commit()
            migrate_db()
            reconciled = database.execute(
                "SELECT status FROM users WHERE id=?", (participant_id,)
            ).fetchone()
            self.assertEqual(reconciled["status"], "activated")
            database.execute(
                "UPDATE users SET status='registered' WHERE id=?", (participant_id,)
            )
            database.execute(
                "UPDATE invitations SET participant_user_id=NULL WHERE id=?",
                (invitation["id"],),
            )
            database.commit()
            migrate_db()
            unchanged = database.execute(
                "SELECT status FROM users WHERE id=?", (participant_id,)
            ).fetchone()
            still_unlinked = database.execute(
                "SELECT participant_user_id FROM invitations WHERE id=?",
                (invitation["id"],),
            ).fetchone()
            self.assertEqual(unchanged["status"], "registered")
            self.assertIsNone(still_unlinked["participant_user_id"])

    def test_development_demo_member_and_admin_credentials(self):
        app.config["SEED_DEMO_DATA"] = True
        with app.app_context():
            init_db()
            database = get_db()
            demo = database.execute(
                "SELECT * FROM users WHERE email = 'demo@khattah.test'"
            ).fetchone()
            admin = database.execute(
                "SELECT * FROM users WHERE email = 'admin@khattah.test'"
            ).fetchone()
            self.assertEqual(demo["name"], "DEMO / DEVELOPMENT Member")
            self.assertEqual(admin["name"], "DEMO / DEVELOPMENT Administrator")
            self.assertEqual(admin["is_admin"], 1)
            invitation_count = database.execute(
                "SELECT COUNT(*) AS count FROM invitations WHERE user_id = ?",
                (demo["id"],),
            ).fetchone()["count"]
            transaction_count = database.execute(
                "SELECT COUNT(*) AS count FROM transactions WHERE user_id = ?",
                (demo["id"],),
            ).fetchone()["count"]
            self.assertGreaterEqual(invitation_count, 4)
            self.assertGreaterEqual(transaction_count, 1)

        member_login = self.client.post(
            "/login",
            data={
                "email": "demo@khattah.test",
                "password": "Demo123!",
                "csrf_token": self.csrf_token("/login"),
            },
        )
        self.assertEqual(member_login.status_code, 302)
        self.assertEqual(member_login.location, "/dashboard")
        self.assertEqual(self.client.get("/admin").status_code, 302)

        self.client.get("/logout")
        admin_login = self.client.post(
            "/login",
            data={
                "email": "admin@khattah.test",
                "password": "Admin123!",
                "csrf_token": self.csrf_token("/login"),
            },
        )
        self.assertEqual(admin_login.status_code, 302)
        self.assertEqual(self.client.get("/admin").status_code, 200)
        self.assertEqual(self.client.get("/demo/admin").status_code, 302)

        app.config["SEED_DEMO_DATA"] = False
        self.client.get("/logout")
        self.assertEqual(self.client.get("/demo").status_code, 404)
        self.assertEqual(self.client.get("/demo/admin").status_code, 404)
        blocked = self.client.post(
            "/login",
            data={
                "email": "demo@khattah.test",
                "password": "Demo123!",
                "csrf_token": self.csrf_token("/login"),
            },
        )
        self.assertEqual(blocked.status_code, 200)

    def test_fixed_demo_otp_completes_registration_only_in_demo_mode(self):
        app.config["SEED_DEMO_DATA"] = True
        response = self.client.post(
            "/register",
            data={
                "name": "Demo OTP Tester",
                "email": "demo.otp@test.local",
                "password": "StrongPass123!",
                "country_code": "+1",
                "mobile_number": "3065550299",
                "csrf_token": self.csrf_token("/register"),
            },
        )
        self.assertEqual(response.status_code, 200)
        with self.client.session_transaction() as session:
            token = session["phone_challenge_token"]
        self.assertEqual(mock_sms_provider.code_for_testing(token), "123456")

        verified = self.client.post(
            "/register/verify",
            data={
                "verification_code": "123456",
                "csrf_token": self.csrf_token("/register"),
            },
        )
        self.assertEqual(verified.status_code, 302)
        self.assertEqual(verified.location, "/dashboard")

        app.config["SEED_DEMO_DATA"] = False
        with app.app_context():
            with patch(
                "services.phone_verification.secrets.randbelow",
                return_value=654321,
            ):
                challenge = request_verification(get_db(), "+1", "3065550298")
            self.assertEqual(
                mock_sms_provider.code_for_testing(challenge["challenge_token"]),
                "654321",
            )
            with self.assertRaises(PhoneVerificationError):
                verify_code(get_db(), challenge["challenge_token"], "123456")

    def test_five_activations_complete_package_and_create_reward(self):
        self.create_invitations(1, 5)
        invitation_ids = self.invitation_ids()
        self.activate(invitation_ids[:4])

        with app.app_context():
            database = get_db()
            circle = database.execute(
                "SELECT status FROM circles WHERE user_id = ?",
                (self.member_id,),
            ).fetchone()
            qualified = database.execute(
                """
                SELECT COUNT(*) AS count FROM circle_participants cp
                JOIN circles c ON c.id = cp.circle_id
                WHERE c.user_id = ?
                """,
                (self.member_id,),
            ).fetchone()["count"]
            reward_count = database.execute(
                "SELECT COUNT(*) AS count FROM rewards WHERE user_id = ?",
                (self.member_id,),
            ).fetchone()["count"]
            self.assertEqual(circle["status"], "active")
            self.assertEqual(qualified, 4)
            self.assertEqual(reward_count, 0)

        self.activate(invitation_ids[4:])
        with app.app_context():
            database = get_db()
            circle = database.execute(
                "SELECT status FROM circles WHERE user_id = ?",
                (self.member_id,),
            ).fetchone()
            reward = database.execute(
                "SELECT status FROM rewards WHERE user_id = ?",
                (self.member_id,),
            ).fetchone()
            self.assertEqual(circle["status"], "completed")
            self.assertEqual(reward["status"], "available")

    def test_configurable_package_count_and_immutable_history_snapshots(self):
        with app.app_context():
            database = get_db()
            save_package_configuration(
                database,
                {
                    "sequence_number": 1,
                    "name_en": "Starter Configured",
                    "name_ar": "الأساسية المضبوطة",
                    "amount": "125.50",
                    "currency": "CAD",
                    "qualifying_count": 3,
                    "reward_amount": "40.00",
                    "reward_currency": "CAD",
                    "reward_config_json": '{"kind":"fixed"}',
                    "display_order": 1,
                    "is_active": "on",
                },
                self.admin_id,
            )
            user = database.execute(
                """
                INSERT INTO users(name,email,password_hash,status,joined_at,is_admin)
                VALUES('Configured Member','configured@test.local',?,'activated','2026-09-18',0)
                """,
                (generate_password_hash("Configured123!"),),
            )
            configured_user_id = user.lastrowid
            database.execute("INSERT INTO settings(user_id) VALUES(?)", (configured_user_id,))
            package = ensure_active_package(database, configured_user_id)
            self.assertEqual(package["required_participants"], 3)
            database.commit()

            from services.khattah import activate_invitation
            for index in range(3):
                invitation = create_invitation(
                    database, configured_user_id, f"configured-{index}@test.local"
                )
                activate_invitation(database, invitation["id"], self.admin_id)
            database.commit()

            completed = database.execute(
                """
                SELECT status, required_participants, amount_minor_snapshot,
                       reward_amount_minor_snapshot
                FROM circles WHERE user_id = ?
                """,
                (configured_user_id,),
            ).fetchone()
            reward = database.execute(
                "SELECT amount_minor, currency FROM rewards WHERE user_id = ?",
                (configured_user_id,),
            ).fetchone()
            self.assertEqual(
                (
                    completed["status"],
                    completed["required_participants"],
                    completed["amount_minor_snapshot"],
                    completed["reward_amount_minor_snapshot"],
                ),
                ("completed", 3, 12550, 4000),
            )
            self.assertEqual((reward["amount_minor"], reward["currency"]), (4000, "CAD"))

            save_package_configuration(
                database,
                {
                    "sequence_number": 1,
                    "name_en": "Starter Future",
                    "name_ar": "الأساسية المستقبلية",
                    "qualifying_count": 7,
                    "display_order": 1,
                    "is_active": "on",
                    "reward_config_json": "{}",
                },
                self.admin_id,
            )
            database.commit()
            unchanged = database.execute(
                "SELECT required_participants, reward_amount_minor_snapshot FROM circles WHERE user_id = ?",
                (configured_user_id,),
            ).fetchone()
            unchanged_reward = database.execute(
                "SELECT amount_minor, currency FROM rewards WHERE user_id = ?",
                (configured_user_id,),
            ).fetchone()
            self.assertEqual(
                (unchanged["required_participants"], unchanged["reward_amount_minor_snapshot"]),
                (3, 4000),
            )
            self.assertEqual(
                (unchanged_reward["amount_minor"], unchanged_reward["currency"]),
                (4000, "CAD"),
            )

        self.login_as(configured_user_id)
        history_page = self.client.get("/packages").get_data(as_text=True)
        self.assertIn("Starter Configured", history_page)
        self.assertNotIn("Starter Future", history_page)

    def test_package_configuration_admin_authorization_and_migration_idempotence(self):
        with app.app_context():
            init_db()
            init_db()
            database = get_db()
            current = database.execute(
                "SELECT sequence_number, qualifying_count FROM package_configurations WHERE is_current=1 ORDER BY sequence_number"
            ).fetchall()
            self.assertEqual([row["sequence_number"] for row in current], [1, 2, 3, 4, 5])
            self.assertTrue(all(row["qualifying_count"] == 5 for row in current))

        self.login_as(self.member_id)
        self.assertEqual(self.client.get("/admin/packages").status_code, 302)
        token = self.csrf_token("/dashboard")
        self.assertEqual(
            self.client.post(
                "/api/v1/admin/package-configurations",
                json={"sequence_number": 6},
                headers={"X-CSRF-Token": token},
            ).status_code,
            403,
        )

        self.login_as(self.admin_id)
        admin_page = self.client.get("/admin/packages")
        self.assertEqual(admin_page.status_code, 200)
        self.assertIn("Starter", admin_page.get_data(as_text=True))

    def test_multiple_packages_are_retained_without_monthly_limit(self):
        self.create_invitations(1, 5)
        self.activate(self.invitation_ids())

        self.login_as(self.member_id)
        response = self.client.post(
            "/packages/new",
            data={"csrf_token": self.csrf_token("/packages")},
        )
        self.assertEqual(response.status_code, 302)

        self.create_invitations(6, 5)
        self.activate(self.invitation_ids()[5:])

        with app.app_context():
            database = get_db()
            circles = database.execute(
                "SELECT sequence_number, status FROM circles WHERE user_id = ? ORDER BY sequence_number",
                (self.member_id,),
            ).fetchall()
            rewards = database.execute(
                "SELECT COUNT(*) AS count FROM rewards WHERE user_id = ?",
                (self.member_id,),
            ).fetchone()["count"]
            self.assertEqual(
                [(row["sequence_number"], row["status"]) for row in circles],
                [(1, "completed"), (2, "completed")],
            )
            self.assertEqual(rewards, 2)

    def test_admin_and_api_authorization(self):
        self.login_as(self.member_id)
        self.assertEqual(self.client.get("/admin").status_code, 302)
        self.assertEqual(
            self.client.get("/api/v1/admin/overview").status_code,
            403,
        )

        self.login_as(self.admin_id)
        self.assertEqual(self.client.get("/admin").status_code, 200)
        self.assertEqual(
            self.client.get("/api/v1/admin/overview").status_code,
            200,
        )

        with self.client.session_transaction() as session:
            session.clear()
        self.assertEqual(self.client.get("/api/v1/dashboard").status_code, 401)

    def test_canonical_package_pages_and_legacy_route_redirect(self):
        self.login_as(self.member_id)
        package_page = self.client.get("/packages")
        self.assertEqual(package_page.status_code, 200)
        package_html = package_page.get_data(as_text=True)
        self.assertIn("My Packages", package_html)
        self.assertIn("Package progress", package_html)
        self.assertNotIn("Circle", package_html)
        self.assertNotIn("دائرة", package_html)

        legacy = self.client.get("/circle")
        self.assertEqual(legacy.status_code, 302)
        self.assertEqual(legacy.location, "/packages")
        self.assertEqual(
            self.client.post(
                "/circle/new",
                data={"csrf_token": self.csrf_token("/packages")},
            ).status_code,
            302,
        )

        package_api = self.client.get("/api/v1/package")
        self.assertEqual(package_api.status_code, 200)
        self.assertIn("current_package", package_api.get_json())
        packages_api = self.client.get("/api/v1/packages")
        self.assertEqual(packages_api.status_code, 200)
        self.assertIn("packages", packages_api.get_json())

        legacy_api = self.client.get("/api/v1/circle")
        self.assertEqual(legacy_api.status_code, 200)
        self.assertIn("current", legacy_api.get_json())
        legacy_history = self.client.get("/api/v1/circles")
        self.assertEqual(legacy_history.status_code, 200)

        for path in (
            "/dashboard",
            "/packages",
            "/invitations",
            "/transactions",
            "/profile",
            "/settings",
        ):
            rendered = self.client.get(path).get_data(as_text=True)
            self.assertNotIn("Circle", rendered)
            self.assertNotIn("دائرة", rendered)

        self.login_as(self.admin_id)
        rendered_admin = self.client.get("/admin").get_data(as_text=True)
        self.assertNotIn("Circle", rendered_admin)
        self.assertNotIn("دائرة", rendered_admin)

    def test_canonical_api_contract_has_no_circle_keys(self):
        self.login_as(self.member_id)
        self.client.get("/api/v1/csrf")
        package = self.client.get("/api/v1/package").get_json()
        packages = self.client.get("/api/v1/packages").get_json()
        token = self.csrf_token("/dashboard")
        with app.app_context():
            get_db().execute(
                "UPDATE circles SET status = 'completed', completed_at = ? WHERE user_id = ?",
                ("2026-09-17T00:00:00+00:00", self.member_id),
            )
            get_db().commit()
        created = self.client.post(
            "/api/v1/packages", headers={"X-CSRF-Token": token}
        )
        self.assertEqual(created.status_code, 201)
        created = created.get_json()

        forbidden = {
            "circle",
            "circles",
            "circle_id",
            "circle_status",
            "current_circle",
            "completed_circle_count",
            "current",
            "history",
        }

        def assert_clean(value):
            if isinstance(value, dict):
                self.assertTrue(forbidden.isdisjoint(value))
                for nested in value.values():
                    assert_clean(nested)
            elif isinstance(value, list):
                for nested in value:
                    assert_clean(nested)

        def assert_package_record(record):
            self.assertIn("package_id", record)
            self.assertIn("package_status", record)
            self.assertIn("package_participants", record)

        assert_clean(package)
        assert_clean(packages)
        assert_clean(created)
        assert_package_record(package["current_package"])
        for record in packages["packages"]:
            assert_package_record(record)
        assert_package_record(created["package"])

        legacy_current = self.client.get("/api/v1/circle").get_json()
        legacy_history = self.client.get("/api/v1/circles").get_json()
        self.assertIn("current", legacy_current)
        self.assertIn("history", legacy_current)
        self.assertIsInstance(legacy_history, list)

    def test_versioned_demo_name_migration_preserves_package_history(self):
        with app.app_context():
            database = get_db()
            admin = database.execute(
                """
                INSERT INTO users
                    (name, email, password_hash, status, joined_at, is_admin)
                VALUES ('Migration Admin', 'migration-admin@test.local', ?, 'activated', '2026-09-17', 1)
                """,
                (generate_password_hash("Admin1234!"),),
            )
            database.execute(
                "INSERT INTO settings (user_id) VALUES (?)", (admin.lastrowid,)
            )
            target = database.execute(
                """
                INSERT INTO users
                    (name, email, password_hash, status, joined_at, is_admin)
                VALUES ('Multiple Circles', 'multiple@khattah.app', ?, 'activated', '2026-09-17', 0)
                """,
                (generate_password_hash("Member1234!"),),
            )
            target_id = target.lastrowid
            database.execute("INSERT INTO settings (user_id) VALUES (?)", (target_id,))
            ensure_active_package(database, target_id)
            package_id = database.execute(
                "SELECT id FROM circles WHERE user_id = ?", (target_id,)
            ).fetchone()["id"]
            create_invitation(database, target_id, "migration-participant")
            database.execute(
                """
                INSERT INTO audit_events
                    (user_id, event_type, description, entity_type, entity_id, occurred_at)
                VALUES (?, 'migration_check', 'Migration check', 'circle', ?, '2026-09-17T00:00:00+00:00')
                """,
                (target_id, package_id),
            )
            database.execute(
                """
                INSERT INTO rewards (user_id, circle_id, status, eligible_at)
                VALUES (?, ?, 'available', '2026-09-17T00:00:00+00:00')
                """,
                (target_id, package_id),
            )
            database.execute(
                "DELETE FROM schema_migrations WHERE version = 201"
            )
            counts_before = {
                table: database.execute(
                    f"SELECT COUNT(*) AS count FROM {table} WHERE user_id = ?",
                    (target_id,),
                ).fetchone()["count"]
                for table in ("circles", "invitations", "audit_events", "rewards")
            }
            before = {
                table: database.execute(
                    f"SELECT id FROM {table} WHERE user_id = ? ORDER BY id",
                    (target_id,),
                ).fetchall()
                for table in ("circles", "invitations", "audit_events", "rewards")
            }
            migrate_db()
            after_name = database.execute(
                "SELECT name FROM users WHERE id = ?", (target_id,)
            ).fetchone()["name"]
            self.assertEqual(after_name, "Multiple Packages")
            for table, rows in before.items():
                after = database.execute(
                    f"SELECT id FROM {table} WHERE user_id = ? ORDER BY id",
                    (target_id,),
                ).fetchall()
                self.assertEqual([row["id"] for row in after], [row["id"] for row in rows])
                self.assertEqual(
                    database.execute(
                        f"SELECT COUNT(*) AS count FROM {table} WHERE user_id = ?",
                        (target_id,),
                    ).fetchone()["count"],
                    counts_before[table],
                )
            self.assertEqual(database.execute("PRAGMA foreign_key_check").fetchall(), [])
            self.assertIsNotNone(
                database.execute(
                    "SELECT 1 FROM schema_migrations WHERE version = 201"
                ).fetchone()
            )

            self.login_as(admin.lastrowid)
            rendered = self.client.get("/admin").get_data(as_text=True)
            self.assertNotIn("Multiple Circles", rendered)
            self.assertIn("Multiple Packages", rendered)

    def test_activation_requires_admin_and_duplicate_is_idempotent(self):
        self.create_invitations(1, 1)
        invitation_id = self.invitation_ids()[0]

        self.login_as(self.member_id)
        response = self.client.post(
            f"/admin/invitations/{invitation_id}/activate",
            data={"csrf_token": self.csrf_token("/")},
        )
        self.assertEqual(response.status_code, 302)

        self.login_as(self.admin_id)
        token = self.csrf_token("/admin")
        first = self.client.post(
            f"/admin/invitations/{invitation_id}/activate",
            data={"csrf_token": token},
        )
        duplicate = self.client.post(
            f"/admin/invitations/{invitation_id}/activate",
            data={"csrf_token": token},
        )
        self.assertEqual(first.status_code, 302)
        self.assertEqual(duplicate.status_code, 302)

        with app.app_context():
            count = get_db().execute(
                "SELECT COUNT(*) AS count FROM activations WHERE invitation_id = ?",
                (invitation_id,),
            ).fetchone()["count"]
            self.assertEqual(count, 1)

    def test_mutations_require_csrf_token(self):
        self.login_as(self.member_id)
        self.assertEqual(
            self.client.post("/invitations", data={"recipient": "Blocked"}).status_code,
            400,
        )
        self.assertEqual(
            self.client.post(
                "/api/v1/invitations",
                json={"recipient": "Blocked"},
            ).status_code,
            400,
        )

    def test_phone_validation_correct_code_and_already_verified(self):
        with app.app_context():
            database = get_db()
            with self.assertRaises(InvalidPhoneError):
                request_verification(database, "+1", "12")

            challenge = request_verification(database, "+1", "306 555 0201")
            code = mock_sms_provider.code_for_testing(challenge["challenge_token"])
            result = verify_code(database, challenge["challenge_token"], code)
            repeated = verify_code(database, challenge["challenge_token"], code)
            database.commit()
            self.assertTrue(result["verified"])
            self.assertFalse(result["already_verified"])
            self.assertTrue(repeated["already_verified"])

    def test_incorrect_code_attempt_limit_and_expiry(self):
        now = datetime(2026, 9, 17, 12, 0, tzinfo=timezone.utc)
        with app.app_context():
            database = get_db()
            challenge = request_verification(
                database, "+1", "3065550202", now=now
            )
            for attempt in range(5):
                with self.assertRaises(PhoneVerificationError):
                    verify_code(
                        database,
                        challenge["challenge_token"],
                        "000000",
                        now=now + timedelta(seconds=attempt),
                    )
            locked = database.execute(
                """
                SELECT status, attempts_remaining
                FROM phone_verification_challenges
                WHERE challenge_token = ?
                """,
                (challenge["challenge_token"],),
            ).fetchone()
            self.assertEqual(locked["status"], "locked")
            self.assertEqual(locked["attempts_remaining"], 0)

            expired = request_verification(
                database, "+1", "3065550203", now=now
            )
            expired_code = mock_sms_provider.code_for_testing(
                expired["challenge_token"]
            )
            with self.assertRaisesRegex(PhoneVerificationError, "expired"):
                verify_code(
                    database,
                    expired["challenge_token"],
                    expired_code,
                    now=now + timedelta(minutes=11),
                )

    def test_resend_limits_and_replaces_code(self):
        now = datetime(2026, 9, 17, 12, 0, tzinfo=timezone.utc)
        with app.app_context():
            database = get_db()
            first = request_verification(
                database, "+1", "3065550204", now=now
            )
            first_code = mock_sms_provider.code_for_testing(
                first["challenge_token"]
            )
            with self.assertRaises(VerificationRateLimitError):
                request_verification(
                    database,
                    "+1",
                    "3065550204",
                    now=now + timedelta(seconds=30),
                )
            resent = request_verification(
                database,
                "+1",
                "3065550204",
                now=now + timedelta(seconds=61),
            )
            new_code = mock_sms_provider.code_for_testing(
                resent["challenge_token"]
            )
            self.assertEqual(first["challenge_token"], resent["challenge_token"])
            self.assertNotEqual(first_code, new_code)
            with self.assertRaises(PhoneVerificationError):
                verify_code(
                    database,
                    resent["challenge_token"],
                    first_code,
                    now=now + timedelta(seconds=62),
                )
            self.assertTrue(
                verify_code(
                    database,
                    resent["challenge_token"],
                    new_code,
                    now=now + timedelta(seconds=63),
                )["verified"]
            )

    def test_duplicate_phone_and_api_does_not_expose_code(self):
        with app.app_context():
            database = get_db()
            database.execute(
                """
                UPDATE users
                SET normalized_phone = '+13065550205',
                    country_calling_code = '+1',
                    phone_verified = 1,
                    phone_verified_at = ?
                WHERE id = ?
                """,
                (datetime.now(timezone.utc).isoformat(), self.member_id),
            )
            database.commit()
            with self.assertRaises(DuplicatePhoneError):
                request_verification(database, "+1", "3065550205")

        response = self.client.post(
            "/api/v1/phone-verification/request",
            json={"country_code": "+1", "mobile_number": "3065550206"},
        )
        self.assertEqual(response.status_code, 201)
        payload = response.get_json()
        self.assertIn("challenge_token", payload)
        self.assertNotIn("verification_code", payload)
        self.assertNotIn("code", payload)
        self.assertNotIn("code_hash", payload)

    def test_api_challenge_cannot_replace_web_registration_challenge(self):
        now = datetime(2026, 9, 17, 12, 0, tzinfo=timezone.utc)
        with app.app_context():
            database = get_db()
            pending = database.execute(
                """
                INSERT INTO pending_registrations (
                    name, email, password_hash, country_calling_code,
                    mobile_number, normalized_phone, created_at, expires_at
                )
                VALUES (?, ?, ?, '+1', ?, ?, ?, ?)
                """,
                (
                    "Pending Member",
                    "pending@test.local",
                    generate_password_hash("StrongPass123!"),
                    "3065550207",
                    "+13065550207",
                    now.isoformat(),
                    (now + timedelta(minutes=30)).isoformat(),
                ),
            )
            pending_id = pending.lastrowid
            web_challenge = request_verification(
                database,
                "+1",
                "3065550207",
                pending_registration_id=pending_id,
                now=now,
            )
            web_code = mock_sms_provider.code_for_testing(
                web_challenge["challenge_token"]
            )
            api_challenge = request_verification(
                database,
                "+1",
                "3065550207",
                pending_registration_id=None,
                now=now + timedelta(seconds=61),
            )
            self.assertNotEqual(
                web_challenge["challenge_token"],
                api_challenge["challenge_token"],
            )
            result = verify_code(
                database,
                web_challenge["challenge_token"],
                web_code,
                now=now + timedelta(seconds=62),
            )
            self.assertEqual(result["pending_registration_id"], pending_id)

    def test_public_phone_api_has_caller_rate_limit(self):
        app.config["PHONE_API_REQUESTS_PER_HOUR"] = 2
        for index, suffix in enumerate(("208", "209")):
            response = self.client.post(
                "/api/v1/phone-verification/request",
                json={
                    "country_code": "+1",
                    "mobile_number": f"3065550{suffix}",
                },
                headers={"User-Agent": f"rotating-agent-{index}"},
                environ_base={"REMOTE_ADDR": "198.51.100.42"},
            )
            self.assertEqual(response.status_code, 201)
        blocked = self.client.post(
            "/api/v1/phone-verification/request",
            json={"country_code": "+1", "mobile_number": "3065550210"},
            headers={"User-Agent": "another-rotating-agent"},
            environ_base={"REMOTE_ADDR": "198.51.100.42"},
        )
        self.assertEqual(blocked.status_code, 429)

    def test_english_and_arabic_locale_rendering_and_switching(self):
        english = self.client.get("/")
        self.assertIn('<html lang="en" dir="ltr"', english.get_data(as_text=True))
        self.assertIn("English", english.get_data(as_text=True))

        switched = self.client.get("/language/ar?next=/")
        self.assertEqual(switched.status_code, 302)
        arabic = self.client.get("/")
        arabic_html = arabic.get_data(as_text=True)
        self.assertIn('<html lang="ar" dir="rtl"', arabic_html)
        self.assertIn("العربية", arabic_html)
        self.assertIn("باقتك.", arabic_html)
        self.assertIn("ابدأ حسابك", arabic_html)

        for path in ("/register", "/login"):
            response = self.client.get(path)
            rendered = response.get_data(as_text=True)
            self.assertIn('<html lang="ar" dir="rtl"', rendered)
            self.assertIn("أنشئ حسابك" if path == "/register" else "سجّل الدخول إلى ختّة", rendered)

        registration = self.client.post(
            "/register",
            data={
                "name": "Arabic Member",
                "email": "arabic@test.local",
                "password": "StrongPass123!",
                "country_code": "+1",
                "mobile_number": "306555 0299",
                "csrf_token": self.csrf_token("/register"),
            },
        )
        registration_html = registration.get_data(as_text=True)
        self.assertIn("رمز التحقق", registration_html)
        self.assertIn("وضع التطوير والاختبار", registration_html)

    def test_logged_in_language_preference_persists_through_pages_logout_login(self):
        self.login_as(self.member_id)
        switched = self.client.get("/language/ar?next=/dashboard")
        self.assertEqual(switched.status_code, 302)
        for path in ("/dashboard", "/packages", "/invitations", "/settings"):
            response = self.client.get(path)
            rendered = response.get_data(as_text=True)
            self.assertIn('<html lang="ar" dir="rtl"', rendered)
            expected = {
                "/dashboard": "نظرة سريعة",
                "/packages": "باقاتي",
                "/invitations": "الدعوات",
                "/settings": "التفضيلات",
            }[path]
            self.assertIn(expected, rendered)
            if path == "/packages":
                self.assertIn(
                    "يملأ المشاركون المدفوعون أو المفعّلون مواضع التأهل المضبوطة",
                    rendered,
                )
                self.assertNotIn(
                    "The first five paid / activated participants",
                    rendered,
                )

        self.login_as(self.admin_id)
        self.client.get("/language/ar?next=/admin")
        admin_page = self.client.get("/admin")
        self.assertIn("إدارة ختّة", admin_page.get_data(as_text=True))
        self.login_as(self.member_id)

        with app.app_context():
            preference = get_db().execute(
                "SELECT preferred_language FROM settings WHERE user_id = ?",
                (self.member_id,),
            ).fetchone()["preferred_language"]
            self.assertEqual(preference, "ar")

        self.client.get("/logout")
        login = self.client.post(
            "/login",
            data={
                "email": "member@test.local",
                "password": "Member1234!",
                "csrf_token": self.csrf_token("/login"),
            },
        )
        self.assertEqual(login.status_code, 302)
        dashboard = self.client.get("/dashboard")
        self.assertIn('<html lang="ar" dir="rtl"', dashboard.get_data(as_text=True))

        back_to_english = self.client.get("/language/en?next=/dashboard")
        self.assertEqual(back_to_english.status_code, 302)
        self.assertIn(
            '<html lang="en" dir="ltr"',
            self.client.get("/dashboard").get_data(as_text=True),
        )

    def test_arabic_dynamic_dashboard_phrases_and_api_errors(self):
        self.login_as(self.member_id)
        self.client.get("/language/ar?next=/dashboard")
        csrf = self.csrf_token("/invitations")
        invitation = self.client.post(
            "/invitations",
            data={"recipient": "Arabic Participant", "invitation_message_id": self.invitation_message_id, "csrf_token": csrf},
        )
        self.assertEqual(invitation.status_code, 302)
        dashboard = self.client.get("/dashboard").get_data(as_text=True)
        self.assertIn("1 دعوة مُرسلة", dashboard)
        self.assertIn("0 تفعيلات تجريبية", dashboard)
        self.assertIn("تم إرسال دعوة إلى Arabic Participant", dashboard)

        api_forbidden = self.client.get("/api/v1/admin/overview")
        self.assertEqual(api_forbidden.status_code, 403)
        self.assertEqual(api_forbidden.get_json()["error"], "يلزم الوصول بصلاحيات المسؤول")

        with self.client.session_transaction() as session:
            session.clear()
        api_unauthorized = self.client.get("/api/v1/dashboard")
        self.assertEqual(api_unauthorized.status_code, 401)
        self.assertEqual(api_unauthorized.get_json()["error"], "المصادقة مطلوبة")

    def test_arabic_dynamic_phrase_interpolation_preserves_values(self):
        cases = {
            "1 / 5 Qualified": "1 / 5 مؤهل",
            "2 mock activations": "2 تفعيلات تجريبية",
            "1 completed package retained in history.": "1 باقة مكتملة محفوظة في السجل.",
            "3 invitations sent": "3 دعوات مُرسلة",
            "Package #4 is ready.": "الباقة #4 جاهزة.",
            "Invitation sent to Amina": "تم إرسال دعوة إلى Amina",
            "Amina qualified in position 2 for Package #4": "Amina تأهل في الموضع 2 للباقة #4",
            "Reward available for Package #4": "المكافأة متاحة للباقة #4",
        }
        for source, expected in cases.items():
            self.assertEqual(translate(source, "ar"), expected)


if __name__ == "__main__":
    unittest.main()