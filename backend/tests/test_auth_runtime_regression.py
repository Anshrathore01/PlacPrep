import uuid
import unittest

from fastapi.testclient import TestClient
from sqlalchemy import text

from app.database import engine
from app.main import app
from app.auth.security import verify_password


class AuthRuntimeRegressionTests(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app)
        self.email = f"runtime_{uuid.uuid4().hex[:10]}@example.com"
        self.admin_email = None
        self.password = "StrongPass123!"
        self.display_name = "Runtime Test User"

    def tearDown(self):
        with engine.begin() as conn:
            conn.execute(
                text("DELETE FROM users WHERE email = :email"),
                {"email": self.email.lower()},
            )
            if self.admin_email is not None:
                conn.execute(
                    text("DELETE FROM users WHERE email = :email"),
                    {"email": self.admin_email.lower()},
                )

    def test_register_route_executes_and_persists_hashed_password(self):
        register_response = self.client.post(
            "/auth/register",
            json={
                "email": self.email,
                "password": self.password,
                "display_name": self.display_name,
            },
        )
        self.assertEqual(register_response.status_code, 201, register_response.text)

        with engine.begin() as conn:
            row = conn.execute(
                text("SELECT user_id, email, password_hash, role, is_active FROM users WHERE email = :email"),
                {"email": self.email.lower()},
            ).mappings().first()

        self.assertIsNotNone(row)
        self.assertEqual(row["email"], self.email.lower())
        self.assertNotEqual(row["password_hash"], self.password)
        self.assertTrue(verify_password(self.password, row["password_hash"]))
        self.assertFalse(verify_password("wrong-password", row["password_hash"]))

        login_response = self.client.post(
            "/auth/login",
            json={"email": self.email, "password": self.password},
        )
        self.assertEqual(login_response.status_code, 200, login_response.text)
        token = login_response.json()["access_token"]
        self.assertTrue(token)

        me_response = self.client.get(
            "/auth/me",
            headers={"Authorization": f"Bearer {token}"},
        )
        self.assertEqual(me_response.status_code, 200, me_response.text)
        self.assertEqual(me_response.json()["email"], self.email.lower())

        dup_response = self.client.post(
            "/auth/register",
            json={
                "email": self.email,
                "password": self.password,
                "display_name": "Duplicate User",
            },
        )
        self.assertEqual(dup_response.status_code, 409, dup_response.text)

        bad_login_response = self.client.post(
            "/auth/login",
            json={"email": self.email, "password": "WrongPassword123!"},
        )
        self.assertEqual(bad_login_response.status_code, 401, bad_login_response.text)

        with engine.begin() as conn:
            conn.execute(
                text("UPDATE users SET is_active = 0 WHERE email = :email"),
                {"email": self.email.lower()},
            )

        inactive_login_response = self.client.post(
            "/auth/login",
            json={"email": self.email, "password": self.password},
        )
        self.assertEqual(inactive_login_response.status_code, 403, inactive_login_response.text)

        self.admin_email = f"admin_{uuid.uuid4().hex[:10]}@example.com"
        admin_password = "AdminPass123!"
        admin_register_response = self.client.post(
            "/auth/register",
            json={
                "email": self.admin_email,
                "password": admin_password,
                "display_name": "Admin User",
            },
        )
        self.assertEqual(admin_register_response.status_code, 201, admin_register_response.text)

        with engine.begin() as conn:
            conn.execute(
                text("UPDATE users SET role = 'ADMIN' WHERE email = :email"),
                {"email": self.admin_email.lower()},
            )

        admin_login_response = self.client.post(
            "/auth/login",
            json={"email": self.admin_email, "password": admin_password},
        )
        self.assertEqual(admin_login_response.status_code, 200, admin_login_response.text)
        admin_token = admin_login_response.json()["access_token"]

        student_response = self.client.get(
            "/admin/mcq-health",
            headers={"Authorization": f"Bearer {token}"},
        )
        self.assertEqual(student_response.status_code, 403, student_response.text)

        admin_response = self.client.get(
            "/admin/mcq-health",
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        self.assertEqual(admin_response.status_code, 200, admin_response.text)


if __name__ == '__main__':
    unittest.main()
