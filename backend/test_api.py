import os
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

# Configure an isolated database before importing the application. This keeps
# the test suite independent from backend/ai_studio.db.
_database = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
_database.close()
os.environ["AI_STUDIO_DB_PATH"] = _database.name
os.environ["APP_ENV"] = "test"
os.environ["JWT_SECRET"] = "test-secret-that-is-at-least-32-bytes"
os.environ["GEMINI_API_KEY"] = "test-key"

from fastapi.testclient import TestClient

import main
from ratelimit import check


class ApiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.client = TestClient(main.app)
        alice = cls.client.post(
            "/api/auth/register",
            json={
                "name": "Alice",
                "email": "alice@example.com",
                "password": "correct-horse-battery",
            },
        )
        bob = cls.client.post(
            "/api/auth/register",
            json={
                "name": "Bob",
                "email": "bob@example.com",
                "password": "correct-horse-battery",
            },
        )
        assert alice.status_code == 201, alice.text
        assert bob.status_code == 201, bob.text
        cls.alice_headers = {
            "Authorization": f"Bearer {alice.json()['access_token']}"
        }
        cls.bob_headers = {
            "Authorization": f"Bearer {bob.json()['access_token']}"
        }

    def test_protected_routes_require_authentication(self):
        response = self.client.get("/api/conversations")
        self.assertEqual(response.status_code, 401)

    def test_conversations_are_isolated_by_user(self):
        created = self.client.post(
            "/api/conversations",
            headers=self.alice_headers,
            json={},
        )
        self.assertEqual(created.status_code, 201)
        conversation_id = created.json()["id"]

        bob_read = self.client.get(
            f"/api/conversations/{conversation_id}/messages",
            headers=self.bob_headers,
        )
        bob_delete = self.client.delete(
            f"/api/conversations/{conversation_id}",
            headers=self.bob_headers,
        )
        self.assertEqual(bob_read.status_code, 404)
        self.assertEqual(bob_delete.status_code, 404)

        alice_list = self.client.get(
            "/api/conversations", headers=self.alice_headers
        )
        bob_list = self.client.get(
            "/api/conversations", headers=self.bob_headers
        )
        self.assertIn(conversation_id, {item["id"] for item in alice_list.json()})
        self.assertNotIn(conversation_id, {item["id"] for item in bob_list.json()})

    def test_chat_persists_and_uses_stored_preferences(self):
        preferences = self.client.patch(
            "/api/me/preferences",
            headers=self.alice_headers,
            json={
                "dietary_preference": "vegan",
                "max_cook_time_minutes": 20,
                "servings": 2,
            },
        )
        self.assertEqual(preferences.status_code, 200)

        with patch.object(
            main.agent,
            "run",
            new=AsyncMock(return_value=SimpleNamespace(output="A vegan recipe")),
        ) as run:
            response = self.client.post(
                "/api/chat",
                headers=self.alice_headers,
                json={"content": "Make dinner"},
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["reply"], "A vegan recipe")
        prompt = run.await_args.args[0]
        self.assertIn("'dietaryPreference': 'vegan'", prompt)

        conversation_id = response.json()["conversation_id"]
        history = self.client.get(
            f"/api/conversations/{conversation_id}/messages",
            headers=self.alice_headers,
        )
        self.assertEqual(history.status_code, 200)
        self.assertEqual([item["role"] for item in history.json()], ["user", "assistant"])

    def test_chat_rejects_client_preference_overrides(self):
        response = self.client.post(
            "/api/chat",
            headers=self.alice_headers,
            json={
                "content": "Make dinner",
                "preferences": {"dietaryPreference": "no-restrictions"},
            },
        )
        self.assertEqual(response.status_code, 422)

    def test_rate_limiter_blocks_after_limit(self):
        key = "test-rate-limit-isolation"
        self.assertTrue(check(key, limit=1, window_seconds=60))
        self.assertFalse(check(key, limit=1, window_seconds=60))


if __name__ == "__main__":
    unittest.main()
