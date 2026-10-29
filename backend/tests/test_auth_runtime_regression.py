import unittest

from fastapi.testclient import TestClient

from app.main import app


class AuthRuntimeRegressionTests(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app)

    def test_current_user_requires_a_bearer_token(self):
        response = self.client.get("/auth/me")
        self.assertEqual(response.status_code, 401)

    def test_malformed_supabase_token_is_rejected_without_database_access(self):
        response = self.client.get(
            "/auth/me",
            headers={"Authorization": "Bearer not-a-jwt"},
        )
        self.assertEqual(response.status_code, 401)

    def test_protected_analytics_route_requires_authentication(self):
        response = self.client.get("/analytics/me/summary")
        self.assertEqual(response.status_code, 401)


if __name__ == "__main__":
    unittest.main()
