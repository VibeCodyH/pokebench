"""xAI subscription route: xai_auth.py sign-in store + XAISubscriptionProvider."""
import io
import json
import os
import tempfile
import time
import unittest
from unittest.mock import Mock, patch

import requests
import urllib3

import providers
import xai_auth

# Captured 2026-10-13 from a real grok-4.7 stream on the subscription route (content trimmed).
REAL_FRAMES = [
    {"id": "2d7997ee", "object": "chat.completion.chunk", "created": 1791901805, "model": "grok-4.7",
     "choices": [{"index": 0, "delta": {"reasoning_content": "The user wants a single-word", "role": "assistant"}}],
     "system_fingerprint": "fp_c60958d81f66f847", "service_tier": "default"},
    {"id": "2d7997ee", "object": "chat.completion.chunk", "created": 1791901805, "model": "grok-4.7",
     "choices": [{"index": 0, "delta": {"content": "ok"}, "finish_reason": "stop"}]},
    {"id": "2d7997ee", "object": "chat.completion.chunk", "created": 1791901805, "model": "grok-4.7",
     "choices": [], "usage": {"prompt_tokens": 1249, "completion_tokens": 1, "total_tokens": 1433,
                              "completion_tokens_details": {"reasoning_tokens": 183}}},
]


def sse(frames):
    body = "".join(f"data: {json.dumps(f)}\n\n" for f in frames) + "data: [DONE]\n\n"
    response = requests.Response()
    response.status_code = 200
    response.headers["Content-Type"] = "text/event-stream"
    response.raw = urllib3.HTTPResponse(body=io.BytesIO(body.encode()), preload_content=False, status=200)
    return response


class XAIAuthFixture(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        patcher = patch.dict(os.environ, {"POKEBENCH_XAI_AUTH_DIR": self.dir.name})
        patcher.start()
        self.addCleanup(patcher.stop)
        self.addCleanup(self.dir.cleanup)

    def write(self, **record):
        with open(os.path.join(self.dir.name, "default.json"), "w") as out:
            json.dump(record, out)


class AuthTests(XAIAuthFixture):
    def test_missing_sign_in_is_a_non_retryable_auth_error(self):
        with self.assertRaises(requests.HTTPError) as caught:
            xai_auth.access_token()
        self.assertTrue(caught.exception.non_retryable)

    def test_fresh_token_is_used_without_a_refresh(self):
        self.write(access_token="live", refresh_token="r1", expires_at=time.time() + 6 * 3600)
        with patch.object(xai_auth.requests, "post") as post:
            self.assertEqual(xai_auth.access_token(), "live")
        post.assert_not_called()

    def test_refresh_saves_the_rotated_refresh_token(self):
        self.write(access_token="old", refresh_token="r1", expires_at=time.time() + 60)
        reply = Mock(ok=True, status_code=200)
        reply.json.return_value = {"access_token": "new", "refresh_token": "r2", "token_type": "Bearer",
                                   "expires_in": 21600}
        with patch.object(xai_auth.requests, "post", return_value=reply) as post:
            self.assertEqual(xai_auth.access_token(), "new")
        self.assertEqual(post.call_args.kwargs["data"]["refresh_token"], "r1")
        with open(os.path.join(self.dir.name, "default.json")) as saved_file:
            saved = json.load(saved_file)
        self.assertEqual(saved["refresh_token"], "r2")

    def test_a_busy_token_endpoint_stays_retryable(self):
        self.write(access_token="old", refresh_token="r1", expires_at=0)
        with patch.object(xai_auth.requests, "post", return_value=Mock(ok=False, status_code=503)):
            with self.assertRaises(requests.HTTPError) as caught:
                xai_auth.access_token()
        self.assertFalse(caught.exception.non_retryable)
        self.assertEqual(caught.exception.response.status_code, 503)

    def test_refresh_failure_stops_the_run_instead_of_retrying(self):
        self.write(access_token="old", refresh_token="dead", expires_at=0)
        with patch.object(xai_auth.requests, "post", return_value=Mock(ok=False, status_code=400)):
            with self.assertRaises(requests.HTTPError) as caught:
                xai_auth.access_token()
        self.assertTrue(caught.exception.non_retryable)


class ProviderTests(XAIAuthFixture):
    def test_registry_builds_it_as_a_priced_seat(self):
        self.write(access_token="live", refresh_token="r1", expires_at=time.time() + 6 * 3600)
        provider = providers.get_provider("xai-subscription", "grok-4.7")
        self.assertIsInstance(provider, providers.XAISubscriptionProvider)
        # xAI bills this route as paid additional usage, so it must not claim subscription billing
        self.assertIsNone(getattr(provider, "billing_mode", None))
        self.assertEqual(provider.route, "xai-subscription")

    def test_construction_fails_before_turn_one_without_a_sign_in(self):
        with self.assertRaises(ValueError):
            providers.XAISubscriptionProvider("grok-4.7")

    def test_each_call_sends_the_current_token_and_records_the_served_model(self):
        self.write(access_token="live", refresh_token="r1", expires_at=time.time() + 6 * 3600)
        provider = providers.XAISubscriptionProvider("grok-4.7")
        with patch.object(providers.requests, "post", return_value=sse(REAL_FRAMES)) as post:
            body = provider._post_stream("https://api.x.ai/v1/chat/completions", {},
                                         {"Authorization": "Bearer " + xai_auth.access_token()})
        self.assertEqual(post.call_args.kwargs["headers"]["Authorization"], "Bearer live")
        self.assertEqual(provider.served_model, "grok-4.7")
        self.assertEqual(body["choices"][0]["message"]["content"], "ok")
        # xAI bills reasoning outside completion_tokens; the inherited _tokens must still add it
        self.assertEqual(provider._tokens(body["usage"]), {"prompt": 1249, "completion": 184})


if __name__ == "__main__":
    unittest.main()
