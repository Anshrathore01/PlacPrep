import unittest
from unittest.mock import MagicMock, patch

from fastapi.testclient import TestClient

from app.auth.dependencies import get_current_user
from app.main import app
from scripts.validate_product_dsa_questions import load_and_validate


class ProductDsaQuestionTests(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app)
        self.user = {"user_id": 734, "email": "dsa-test@example.com", "role": "STUDENT", "is_active": 1}
        app.dependency_overrides[get_current_user] = lambda: self.user

    def tearDown(self):
        app.dependency_overrides.pop(get_current_user, None)

    def test_catalog_has_exactly_200_unique_valid_questions(self):
        questions = load_and_validate()
        self.assertEqual(len(questions), 200)
        self.assertEqual(len({question["url"] for question in questions}), 200)
        self.assertIn("Union-Find / DSU", {question["topic"] for question in questions})
        self.assertNotIn("is_completed", questions[0])

    @patch("app.routers.coding_practice.engine.connect")
    def test_catalog_overlays_only_requesting_users_completion_state(self, connect):
        connection = MagicMock()
        connect.return_value.__enter__.return_value = connection
        connection.execute.return_value.scalars.return_value.all.return_value = ["product-dsa-001", "service-only-id"]

        response = self.client.get("/coding-practice/product")

        self.assertEqual(response.status_code, 200, response.text)
        body = response.json()
        self.assertEqual(body["total"], 200)
        self.assertEqual(body["completed"], 1)
        self.assertEqual(body["remaining"], 199)
        self.assertTrue(body["questions"][0]["is_completed"])
        self.assertFalse(body["questions"][1]["is_completed"])
        self.assertEqual(connection.execute.call_args.args[1], {"user_id": self.user["user_id"]})

    @patch("app.routers.coding_practice.engine.begin")
    def test_existing_progress_endpoint_accepts_product_question_and_uncheck(self, begin):
        response = self.client.put("/coding-practice/progress/product-dsa-001", json={"is_solved": False})
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json(), {"problem_id": "product-dsa-001", "is_solved": False})
        begin.return_value.__enter__.return_value.execute.assert_called_once()

    def test_progress_endpoints_require_authentication(self):
        app.dependency_overrides.pop(get_current_user, None)
        self.assertIn(self.client.get("/coding-practice/product").status_code, {401, 403})
        self.assertIn(self.client.put("/coding-practice/progress/product-dsa-001", json={"is_solved": True}).status_code, {401, 403})


if __name__ == "__main__":
    unittest.main()
