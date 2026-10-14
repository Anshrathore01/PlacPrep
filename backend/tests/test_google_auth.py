import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

from app.main import app
from app.auth.dependencies import get_current_user


class GoogleAuthTests(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app)
        self.payload = {"credential": "opaque-google-id-token-value-long-enough", "nonce": "a" * 64}
        self.identity = {"sub": "google-sub-123", "email": "new@example.com", "name": "New Student", "picture": None}
        self.user = {"user_id": 92, "email": "new@example.com", "role": "STUDENT", "is_active": 1}

    @patch("app.auth.router.engine.begin")
    @patch("app.auth.router.service.create_google_user")
    @patch("app.auth.router.service.consume_google_nonce", return_value=True)
    @patch("app.auth.router.service.get_user_by_email", return_value=None)
    @patch("app.auth.router.service.find_user_by_google_id", return_value=None)
    @patch("app.auth.router.verify_google_credential")
    def test_new_google_user_receives_existing_application_jwt(self, verify, find, by_email, consume, create, begin):
        verify.return_value = self.identity
        create.return_value = self.user
        response = self.client.post("/auth/google", json=self.payload)
        self.assertEqual(response.status_code, 200, response.text)
        self.assertTrue(response.json()["access_token"])
        find.assert_called_once()
        create.assert_called_once()

    @patch("app.auth.router.engine.begin")
    @patch("app.auth.router.service.find_user_by_google_id")
    @patch("app.auth.router.service.consume_google_nonce", return_value=True)
    @patch("app.auth.router.verify_google_credential")
    def test_repeat_google_login_finds_and_reuses_existing_user(self, verify, consume, find, begin):
        verify.return_value = self.identity
        find.return_value = self.user
        response = self.client.post("/auth/google", json=self.payload)
        self.assertEqual(response.status_code, 200, response.text)
        self.assertTrue(response.json()["access_token"])

    @patch("app.auth.router.engine.begin")
    @patch("app.auth.router.service.get_user_by_email", return_value={"user_id": 3, "email": "new@example.com"})
    @patch("app.auth.router.service.find_user_by_google_id", return_value=None)
    @patch("app.auth.router.service.consume_google_nonce", return_value=True)
    @patch("app.auth.router.verify_google_credential")
    def test_password_account_email_match_requires_explicit_link(self, verify, consume, find, by_email, begin):
        verify.return_value = self.identity
        response = self.client.post("/auth/google", json=self.payload)
        self.assertEqual(response.status_code, 409)
        self.assertIn("Sign in with your password", response.json()["detail"])

    @patch("app.auth.router.verify_google_credential", side_effect=__import__("fastapi").HTTPException(401, "Invalid or expired Google credential"))
    def test_invalid_and_expired_google_credentials_are_rejected(self, verify):
        for token in ("invalid", "expired"):
            response = self.client.post("/auth/google", json={**self.payload, "credential": token * 20})
            self.assertEqual(response.status_code, 401)

    def test_google_verifier_checks_nonce_and_verified_email(self):
        # Detailed claim checks are tested without relying on Google network keys.
        from app.auth import router
        claims = {"iss": "https://accounts.google.com", "sub": "abc", "email": "a@example.com", "email_verified": True, "nonce": self.payload["nonce"]}
        with patch.dict("os.environ", {"GOOGLE_CLIENT_ID": "client-id"}), patch("google.oauth2.id_token.verify_oauth2_token", return_value=claims):
            self.assertEqual(router.verify_google_credential(self.payload["credential"], self.payload["nonce"])["sub"], "abc")
            with self.assertRaises(__import__("fastapi").HTTPException):
                router.verify_google_credential(self.payload["credential"], "wrong-nonce-123456")

    @patch("app.auth.router.engine.begin")
    @patch("app.auth.router.service.attach_google_identity")
    @patch("app.auth.router.service.find_user_by_google_id", return_value=None)
    @patch("app.auth.router.service.consume_google_nonce", return_value=True)
    @patch("app.auth.router.verify_google_credential")
    def test_signed_in_password_user_can_link_matching_google_identity(self, verify, consume, find, attach, begin):
        verify.return_value = self.identity
        attach.return_value = self.user
        app.dependency_overrides[get_current_user] = lambda: self.user
        try:
            response = self.client.post("/auth/google/link", json=self.payload)
        finally:
            app.dependency_overrides.pop(get_current_user, None)
        self.assertEqual(response.status_code, 200, response.text)
        attach.assert_called_once()

    @patch("app.auth.router.engine.begin")
    @patch("app.auth.router.service.consume_google_nonce", return_value=False)
    @patch("app.auth.router.verify_google_credential")
    def test_google_nonce_is_single_use(self, verify, consume, begin):
        verify.return_value = self.identity
        response = self.client.post("/auth/google", json=self.payload)
        self.assertEqual(response.status_code, 401)


if __name__ == "__main__":
    unittest.main()
