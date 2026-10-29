import json
import time
import unittest
import uuid
from types import SimpleNamespace
from unittest.mock import patch

import jwt
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi import HTTPException

from app.auth import supabase_tokens
from app.auth import service as auth_service


class FakeResponse:
    def __init__(self, body):
        self.body = body

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return None

    def read(self):
        return self.body


class SupabaseTokenTests(unittest.TestCase):
    def setUp(self):
        self.subject = str(uuid.uuid4())
        self.issuer = "https://local-test.supabase.co/auth/v1"
        self.private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        self.public_key = self.private_key.public_key()
        self.claims = {
            "sub": self.subject,
            "iss": self.issuer,
            "aud": "authenticated",
            "exp": int(time.time()) + 300,
            "email": "student@example.test",
        }

    def issue(self, claims=None, key=None):
        return jwt.encode(claims or self.claims, key or self.private_key, algorithm="RS256", headers={"kid": "test-key"})

    def test_valid_asymmetric_token_is_verified_against_supabase_claims(self):
        client = SimpleNamespace(get_signing_key_from_jwt=lambda token: SimpleNamespace(key=self.public_key))
        with patch.object(supabase_tokens, "SUPABASE_URL", "https://local-test.supabase.co"), patch.object(supabase_tokens, "JWKS_CLIENT", client):
            verified = supabase_tokens.verify_supabase_access_token(self.issue())
        self.assertEqual(verified["sub"], self.subject)

    def test_verified_identity_mapping_keeps_existing_numeric_user_and_role(self):
        existing = {
            "user_id": 37,
            "email": "student@example.test",
            "display_name": "Existing Student",
            "role": "ADMIN",
            "is_active": 1,
            "supabase_user_id": None,
        }

        class FakeConnection:
            def __init__(self):
                self.updated_id = None

            def execute(self, statement, params):
                sql = str(statement)
                if sql.startswith("UPDATE"):
                    self.updated_id = params["supabase_user_id"]
                    row = None
                elif "WHERE email =" in sql:
                    row = existing
                elif "WHERE user_id =" in sql:
                    row = {**existing, "supabase_user_id": self.updated_id}
                else:
                    row = None
                return SimpleNamespace(mappings=lambda: SimpleNamespace(first=lambda: row))

        connection = FakeConnection()
        identity = {"sub": self.subject, "email": "student@example.test"}
        verified = {"id": self.subject, "email": "student@example.test", "email_confirmed_at": "2026-10-01T00:00:00Z"}
        mapped = auth_service.resolve_supabase_user(connection, identity, verified)
        self.assertEqual(mapped["user_id"], 37)
        self.assertEqual(mapped["role"], "ADMIN")
        self.assertEqual(connection.updated_id, self.subject)

    def test_unverified_email_cannot_be_mapped_to_existing_user(self):
        identity = {"sub": self.subject, "email": "student@example.test"}
        verified = {"id": self.subject, "email": "student@example.test", "email_confirmed_at": None}
        with self.assertRaises(HTTPException):
            auth_service.resolve_supabase_user(SimpleNamespace(), identity, verified)

    def test_racing_identity_link_cannot_return_another_supabase_users_row(self):
        existing = {"user_id": 37, "email": "student@example.test", "supabase_user_id": None}

        class RacingConnection:
            def execute(self, statement, params):
                sql = str(statement)
                if "WHERE email =" in sql:
                    row = existing
                elif "WHERE user_id =" in sql:
                    row = {**existing, "supabase_user_id": str(uuid.uuid4())}
                else:
                    row = None
                return SimpleNamespace(mappings=lambda: SimpleNamespace(first=lambda: row))

        identity = {"sub": self.subject, "email": "student@example.test"}
        verified = {"id": self.subject, "email": "student@example.test", "email_confirmed_at": "2026-10-01T00:00:00Z"}
        with self.assertRaises(HTTPException) as raised:
            auth_service.resolve_supabase_user(RacingConnection(), identity, verified)
        self.assertEqual(raised.exception.status_code, 409)

    def test_wrong_audience_issuer_expiry_and_signature_are_rejected(self):
        client = SimpleNamespace(get_signing_key_from_jwt=lambda token: SimpleNamespace(key=self.public_key))
        cases = [
            {**self.claims, "aud": "anon"},
            {**self.claims, "iss": "https://wrong.example/auth/v1"},
            {**self.claims, "exp": int(time.time()) - 1},
        ]
        with patch.object(supabase_tokens, "SUPABASE_URL", "https://local-test.supabase.co"), patch.object(supabase_tokens, "JWKS_CLIENT", client):
            for claims in cases:
                with self.subTest(claim=claims), self.assertRaises(HTTPException):
                    supabase_tokens.verify_supabase_access_token(self.issue(claims))
            wrong_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
            with self.assertRaises(HTTPException):
                supabase_tokens.verify_supabase_access_token(self.issue(key=wrong_key))

    def test_legacy_hs256_tokens_require_supabase_auth_user_validation(self):
        secret = "local-test-shared-secret-with-more-than-32-bytes"
        claims = {**self.claims, "iss": self.issuer}
        token = jwt.encode(claims, secret, algorithm="HS256")
        body = json.dumps({"id": self.subject, "email": "student@example.test"}).encode()
        response = FakeResponse(body)
        with patch.object(supabase_tokens, "SUPABASE_URL", "https://local-test.supabase.co"), \
             patch.object(supabase_tokens, "SUPABASE_PUBLISHABLE_KEY", "publishable-test-key"), \
             patch.object(supabase_tokens.urllib.request, "urlopen", return_value=response):
            verified = supabase_tokens.verify_supabase_access_token(token)
        self.assertEqual(verified["sub"], self.subject)

    def test_missing_or_mismatched_supabase_user_is_rejected(self):
        token = jwt.encode(self.claims, "local-test-shared-secret-with-more-than-32-bytes", algorithm="HS256")
        body = json.dumps({"id": str(uuid.uuid4()), "email": "other@example.test"}).encode()
        response = FakeResponse(body)
        with patch.object(supabase_tokens, "SUPABASE_URL", "https://local-test.supabase.co"), \
             patch.object(supabase_tokens, "SUPABASE_PUBLISHABLE_KEY", "publishable-test-key"), \
             patch.object(supabase_tokens.urllib.request, "urlopen", return_value=response), \
             self.assertRaises(HTTPException):
            supabase_tokens.verify_supabase_access_token(token)


if __name__ == "__main__":
    unittest.main()
