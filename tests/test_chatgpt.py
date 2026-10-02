"""Offline subscription contract/security tests; no credentials or model calls."""
import copy
import json
import os
from pathlib import Path
import tempfile
import time
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

import jwt
from cryptography.hazmat.primitives.asymmetric import rsa
import requests

import chatgpt_auth as auth
from chatgpt_provider import ChatGPTProvider
from providers import get_provider
import run_benchmark as runner

SCHEMA = {"type": "object", "properties": {"thought": {"type": "string"},
          "actions": {"type": "array", "items": {"type": "string"}}}, "required": ["actions"]}
PLAN = {"thought": "Pallet Town", "actions": ["wait_60"]}


def completion(model="test-model-snapshot"):
    return {"type": "response.completed", "response": {
        "status": "completed", "model": model,
        "usage": {"input_tokens": 210, "output_tokens": 130},
        "output": [{"type": "message", "content": [
            {"type": "output_text", "text": json.dumps(PLAN)}]}],
    }}


def stream(*events):
    lines = [line for event in events for line in ("data: " + json.dumps(event), "")]
    response = Mock(ok=True)
    response.iter_lines.return_value = iter(lines)
    return response


class CredentialFixture(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.env = patch.dict(os.environ, {"POKEBENCH_CHATGPT_AUTH_DIR": self.directory.name,
                                          "POKEBENCH_CHATGPT_PROFILE": "test"})
        self.env.start()
        self.addCleanup(self.env.stop)
        self.credentials = auth.Credentials()
        self.record = {"client_id": "oaiapp_test", "subject": "user-test", "access_token": "fake-old-access",
                       "refresh_token": "fake-old-refresh", "scopes": [auth.PLAN_SCOPE],
                       "expires_at": time.time() + 3600}
        auth._atomic_json(self.credentials.path, self.record)


class AuthTests(CredentialFixture):
    def test_private_atomic_credentials_and_stable_host(self):
        self.assertEqual(self.credentials.path.stat().st_mode & 0o777, 0o600)
        self.assertEqual(self.credentials.host_id(), auth.Credentials().host_id())
        self.assertNotEqual(auth.Credentials("another-account").path, self.credentials.path)
        with self.assertRaises(ValueError):
            auth.Credentials("../escape")

    @patch("chatgpt_auth.requests.post")
    def test_refresh_rotates_tokens_once_and_retains_account(self, post):
        self.record["expires_at"] = 0
        auth._atomic_json(self.credentials.path, self.record)
        post.return_value = Mock(ok=True, json=lambda: {
            "access_token": "fake-new-access", "refresh_token": "fake-new-refresh",
            "expires_in": 3600, "token_type": "Bearer",
        })
        self.assertEqual(self.credentials.access_token(), "fake-new-access")
        self.assertEqual(self.credentials.access_token(), "fake-new-access")
        post.assert_called_once()
        self.assertEqual(post.call_args.kwargs["data"]["client_id"], "oaiapp_test")
        self.assertNotIn("scope", post.call_args.kwargs["data"])
        saved = self.credentials.read()
        self.assertEqual(saved["subject"], "user-test")
        self.assertEqual(saved["refresh_token"], "fake-new-refresh")

    @patch("chatgpt_auth.requests.post")
    def test_terminal_refresh_error_clears_tokens_but_keeps_registration(self, post):
        self.record["expires_at"] = 0
        auth._atomic_json(self.credentials.path, self.record)
        post.return_value = Mock(ok=False, status_code=400, json=lambda: {"error": "invalid_grant"})
        with self.assertRaises(requests.HTTPError) as raised:
            self.credentials.access_token()
        self.assertEqual(raised.exception.response.status_code, 401)
        saved = self.credentials.read()
        self.assertNotIn("access_token", saved)
        self.assertEqual(saved["client_id"], "oaiapp_test")

    @patch("chatgpt_auth.requests.post")
    def test_transient_refresh_error_preserves_credentials(self, post):
        self.record["expires_at"] = 0
        auth._atomic_json(self.credentials.path, self.record)
        post.return_value = Mock(ok=False, status_code=503, json=lambda: {"error": "unavailable"})
        with self.assertRaises(requests.HTTPError):
            self.credentials.access_token()
        self.assertEqual(self.credentials.read(), self.record)

    @patch("chatgpt_auth.requests.post")
    def test_callback_state_and_client_mismatch_never_exchange(self, post):
        for query in ({"state": "wrong", "client_id": "oaiapp_test", "code": "fake"},
                      {"state": "right", "client_id": "oaiapp_other", "code": "fake"}):
            with self.assertRaises(requests.HTTPError):
                auth.finish_login(self.credentials, self.record, query, "right", "nonce", "verifier", "redirect")
        post.assert_not_called()
        self.assertEqual(self.credentials.read(), self.record)

    @patch("chatgpt_auth.requests.post")
    def test_missing_plan_permission_never_requests_token(self, post):
        self.record["scopes"] = ["openid"]
        auth._atomic_json(self.credentials.path, self.record)
        with self.assertRaises(requests.HTTPError):
            self.credentials.access_token()
        post.assert_not_called()

    @patch("chatgpt_auth.validate_identity", return_value={"sub": "user-test"})
    @patch("chatgpt_auth.requests.post")
    def test_new_login_exchanges_issued_client_and_checks_returned_scope(self, post, validate):
        body = {"access_token": "fake-access", "refresh_token": "fake-refresh",
                "id_token": "fake-id", "scope": auth.SCOPES,
                "expires_in": 3600, "token_type": "Bearer"}
        post.return_value = Mock(ok=True, json=lambda: body)
        query = {"state": "state", "client_id": "oaiapp_new", "code": "fake-code"}
        auth.finish_login(self.credentials, {}, query, "state", "nonce", "verifier", "redirect")
        self.assertEqual(post.call_args.kwargs["data"], {
            "grant_type": "authorization_code", "client_id": "oaiapp_new",
            "code": "fake-code", "code_verifier": "verifier",
            "redirect_uri": "redirect", "resource": auth.RESOURCE,
        })
        validate.assert_called_once_with("fake-id", "oaiapp_new", "nonce")
        saved = self.credentials.read()
        self.assertEqual(saved["client_id"], "oaiapp_new")
        self.assertEqual(saved["subject"], "user-test")
        del body["scope"]
        with self.assertRaises(requests.HTTPError):
            auth.finish_login(self.credentials, saved, query, "state", "nonce", "verifier", "redirect")
        self.assertNotIn(auth.PLAN_SCOPE, self.credentials.read()["scopes"])

    @patch("chatgpt_auth.validate_identity", return_value={"sub": "another-user"})
    @patch("chatgpt_auth.requests.post")
    def test_returning_login_cannot_replace_another_accounts_credentials(self, post, validate):
        post.return_value = Mock(ok=True, json=lambda: {"id_token": "fake-id"})
        with self.assertRaises(requests.HTTPError):
            auth.finish_login(self.credentials, self.record,
                              {"state": "state", "code": "fake-code"},
                              "state", "nonce", "verifier", "redirect")
        self.assertEqual(self.credentials.read(), self.record)

    def test_real_signed_id_token_checks_audience_issuer_expiration_nonce_and_signature(self):
        key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        claims = {"sub": "user-test", "iss": auth.ISSUER, "aud": "oaiapp_test",
                  "exp": int(time.time()) + 300, "nonce": "expected"}
        client = Mock()
        client.get_signing_key_from_jwt.return_value = SimpleNamespace(key=key.public_key())
        with patch("jwt.PyJWKClient", return_value=client):
            valid = jwt.encode(claims, key, algorithm="RS256")
            self.assertEqual(auth.validate_identity(valid, "oaiapp_test", "expected")["sub"], "user-test")
            for field, value in (("aud", "other"), ("iss", "https://evil.example"),
                                 ("exp", 1), ("nonce", "wrong")):
                token = jwt.encode(dict(claims, **{field: value}), key, algorithm="RS256")
                with self.subTest(field=field), self.assertRaises((jwt.PyJWTError, requests.HTTPError)):
                    auth.validate_identity(token, "oaiapp_test", "expected")
            forged = jwt.encode(claims, "not-an-rsa-key" * 3, algorithm="HS256")
            with self.assertRaises(jwt.PyJWTError):
                auth.validate_identity(forged, "oaiapp_test", "expected")


class ProviderTests(CredentialFixture):
    @patch("chatgpt_provider.requests.post")
    def test_exact_harness_content_and_no_extra_tools_or_state(self, post):
        post.return_value = stream(completion())
        provider = get_provider("chatgpt", "test-model")
        original_schema = copy.deepcopy(SCHEMA)
        plan, _, usage = provider.chat("EXACT SYSTEM", "EXACT HISTORY", "PNG_BYTES", SCHEMA, "high")
        payload = post.call_args.kwargs["json"]
        self.assertEqual(payload["instructions"], "EXACT SYSTEM")
        self.assertEqual(payload["input"][0]["content"], [
            {"type": "input_text", "text": "EXACT HISTORY"},
            {"type": "input_image", "image_url": "data:image/png;base64,PNG_BYTES"}])
        self.assertEqual(set(payload), {"model", "instructions", "input", "store", "stream", "text", "reasoning"})
        self.assertEqual(payload["reasoning"], {"effort": "high"})
        self.assertFalse(payload["store"])
        self.assertEqual(SCHEMA, original_schema)
        self.assertEqual(plan, PLAN)
        self.assertEqual(usage, {"prompt": 210, "completion": 130})
        self.assertIsNone(provider.cost(usage))
        self.assertEqual(provider.served_model, "test-model-snapshot")
        self.assertEqual(post.call_args.args, (auth.RESOURCE + "/responses",))
        post.return_value.close.assert_called_once()

    @patch("chatgpt_provider.requests.post")
    def test_completed_items_supply_output_when_terminal_snapshot_is_empty(self, post):
        completed = completion()
        item = completed["response"]["output"].pop()
        done = {"type": "response.output_item.done", "output_index": 0, "item": item}
        post.return_value = stream(done, completed)
        plan, _, usage = ChatGPTProvider("test").chat("s", "u", "img", SCHEMA, "high")
        self.assertEqual(plan, PLAN)
        self.assertEqual(usage, {"prompt": 210, "completion": 130})
        for events in ((done,), ({"type": "response.output_text.delta", "delta": json.dumps(PLAN)}, completed),
                       (dict(done, output_index=1), completed)):
            post.return_value = stream(*events)
            with self.assertRaises(ValueError):
                ChatGPTProvider("test").chat("s", "u", "img", SCHEMA, "high")

    @patch("chatgpt_provider.requests.post")
    def test_truncated_stream_and_missing_usage_never_return_plan(self, post):
        invalid = completion()
        invalid["response"].pop("usage")
        for response in (stream({"type": "response.output_text.delta", "delta": json.dumps(PLAN)}),
                         stream(invalid), stream({"type": "response.incomplete"})):
            post.return_value = response
            with self.assertRaises(ValueError):
                ChatGPTProvider("test").chat("s", "u", "img", SCHEMA, "high")
            response.close.assert_called_once()

    @patch("chatgpt_provider.requests.post")
    def test_subscription_limit_is_terminal_without_paid_key_fallback(self, post):
        post.return_value = stream({"type": "response.failed", "response": {"error": {
            "code": "subscription_sharing_usage_limit_exceeded", "message": "Plan limit"}}})
        with patch.dict(os.environ, {"OPENAI_API_KEY": "must-not-use"}):
            with self.assertRaises(requests.HTTPError) as raised:
                ChatGPTProvider("test").chat("s", "u", "img", SCHEMA, "high")
        self.assertTrue(raised.exception.non_retryable)
        self.assertEqual(raised.exception.response.status_code, 429)
        self.assertNotIn("must-not-use", str(post.call_args))
        post.assert_called_once()

    @patch("chatgpt_provider.requests.post")
    def test_changed_model_and_tool_output_rejected(self, post):
        provider = ChatGPTProvider("test")
        post.return_value = stream(completion("snapshot-a"))
        provider.chat("s", "u", "img", SCHEMA, "high")
        post.return_value = stream(completion("snapshot-b"))
        with self.assertRaises(ValueError) as raised:
            provider.chat("s", "u", "img", SCHEMA, "high")
        self.assertTrue(raised.exception.non_retryable)
        invalid = completion()
        invalid["response"]["output"] = [{"type": "function_call", "name": "shell"}]
        post.return_value = stream(invalid)
        with self.assertRaises(ValueError):
            ChatGPTProvider("test").chat("s", "u", "img", SCHEMA, "high")

    @patch("chatgpt_provider.requests.post")
    def test_output_volume_and_deadline_guards(self, post):
        post.return_value = stream({"type": "response.output_text.delta", "delta": "x" * 51})
        with self.assertRaises(TimeoutError) as raised:
            ChatGPTProvider("test", max_call_chars=50).chat("s", "u", "img", SCHEMA, "high")
        self.assertIn("max_call_chars=50", str(raised.exception))
        post.return_value = stream(completion())
        provider = ChatGPTProvider("test")
        with patch("chatgpt_provider.time.monotonic", side_effect=[0, 1000]):
            with self.assertRaises(TimeoutError):
                provider.chat("s", "u", "img", SCHEMA, "high")

    def test_unsupported_cap_and_fake_prices_rejected(self):
        for opts in ({"max_tokens": 10}, {"input_cost_per_mtok": 1}):
            with self.assertRaises(ValueError):
                ChatGPTProvider("test", **opts)

    def test_summary_records_subscription_and_served_model(self):
        provider = ChatGPTProvider("test")
        provider.served_model = "test-snapshot"
        model = {"provider": "chatgpt", "api_model_id": "test", "family": "gpt",
                 "think": "high", "num_ctx": 65536}
        tracker = SimpleNamespace(summary=lambda: {"furthest_label": "start", "furthest_index": 0})
        path = runner.write_summary(self.directory.name, "test", model, provider, "probe", tracker,
                                    0, 1000, {"prompt": 210, "completion": 130}, 1, "", None)
        summary = json.loads(Path(path).read_text())
        self.assertEqual(summary["billing_mode"], "subscription")
        self.assertEqual(summary["served_model"], "test-snapshot")
        self.assertIsNone(summary["cost_usd"])
        self.assertEqual(summary["execution_route"], provider.route)


if __name__ == "__main__":
    unittest.main()
