"""PokéBench xAI subscription sign-in (SuperGrok / X Premium+ / X Subscription plans).

Lets a Grok seat run on the account's plan instead of XAI_API_KEY, the way chatgpt_auth.py does
for ChatGPT. xAI has no dynamic client registration (auth.x.ai's discovery document lists no
registration_endpoint), so this uses the shared Grok CLI public client that Hermes Agent and
OpenClaw also use; the consent screen names Grok Build. Device-code flow (RFC 8628), no local
callback. Tokens stay outside the repo, one file per runtime.

    python3 xai_auth.py login
    python3 xai_auth.py models
    python3 xai_auth.py probe --model grok-4.7 --image frame.png --think high
"""
import argparse
from contextlib import contextmanager
import base64
import fcntl
import json
import os
from pathlib import Path
import time

import requests

from chatgpt_auth import _atomic_json, auth_error

ISSUER = "https://auth.x.ai"
DEVICE_CODE = ISSUER + "/oauth2/device/code"
TOKEN = ISSUER + "/oauth2/token"
CLIENT_ID = "b1a00492-073a-47ea-816f-4c329264a828"   # shared Grok CLI public client
SCOPES = "openid profile email offline_access grok-cli:access api:access"
API = "https://api.x.ai/v1"
DEVICE_GRANT = "urn:ietf:params:oauth:grant-type:device_code"
REFRESH_EARLY_S = 3600   # access tokens live ~6h


def _directory():
    directory = Path(os.environ.get("POKEBENCH_XAI_AUTH_DIR", "~/.config/pokebench/xai")).expanduser()
    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    return directory


@contextmanager
def _locked():
    # A rotating refresh token must not race between a probe and a runner.
    fd = os.open(_directory() / "default.lock", os.O_CREAT | os.O_RDWR, 0o600)
    with os.fdopen(fd, "w") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        yield


def _read():
    path = _directory() / "default.json"
    return json.loads(path.read_text()) if path.exists() else {}


def _save(body, previous=None):
    if not body.get("access_token") or str(body.get("token_type", "")).lower() != "bearer":
        raise auth_error("xAI returned an incomplete token set", code="xai_auth_required")
    record = dict(previous or {})
    record.update(access_token=body["access_token"],
                  refresh_token=body.get("refresh_token") or record.get("refresh_token"),
                  scopes=body.get("scope", record.get("scopes", "")),
                  expires_at=time.time() + float(body.get("expires_in", 0)))
    _atomic_json(_directory() / "default.json", record)
    return record


def signed_in():
    return bool(_read().get("access_token"))


def access_token():
    """Current bearer, refreshed an hour before expiry. Raises a non-retryable HTTP-shaped
    error the runner already knows how to stop on, never SystemExit."""
    with _locked():
        record = _read()
        if not record.get("access_token"):
            raise auth_error("Sign in first: python3 xai_auth.py login", code="xai_auth_required")
        if time.time() < record.get("expires_at", 0) - REFRESH_EARLY_S:
            return record["access_token"]
        response = requests.post(TOKEN, data={"grant_type": "refresh_token", "client_id": CLIENT_ID,
                                              "refresh_token": record.get("refresh_token", "")},
                                 headers={"Accept": "application/json"}, timeout=30)
        if response.status_code in {400, 401, 403}:
            raise auth_error("xAI session refresh failed; run xai_auth.py login again",
                             response.status_code, code="xai_auth_required")
        if not response.ok:
            # 429 / 5xx: keep the real status so auth_error leaves it retryable.
            raise auth_error(f"xAI token endpoint unavailable (HTTP {response.status_code})",
                             response.status_code, code="xai_refresh_unavailable")
        return _save(response.json(), record)["access_token"]


def login():
    device = requests.post(DEVICE_CODE, data={"client_id": CLIENT_ID, "scope": SCOPES},
                           headers={"Accept": "application/json"}, timeout=30)
    device.raise_for_status()
    device = device.json()
    print(f"Approve in your browser: {device.get('verification_uri_complete') or device['verification_uri']}\n"
          f"Code: {device['user_code']}", flush=True)
    interval = max(1, int(device.get("interval", 5)))
    deadline = time.monotonic() + float(device["expires_in"])
    while time.monotonic() < deadline:
        time.sleep(interval)
        response = requests.post(TOKEN, data={"grant_type": DEVICE_GRANT, "client_id": CLIENT_ID,
                                              "device_code": device["device_code"]},
                                 headers={"Accept": "application/json"}, timeout=30)
        body = response.json() if response.content else {}
        if response.ok:
            with _locked():
                record = _save(body)
            print(f"Signed in. Scopes granted: {record['scopes'] or '(none listed)'}")
            return
        error = body.get("error")
        if error == "authorization_pending":
            continue
        if error == "slow_down":
            interval += 5
            continue
        raise SystemExit(f"Sign-in failed: HTTP {response.status_code} {error or ''}".strip())
    raise SystemExit("Sign-in timed out; run login again")


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("login")
    commands.add_parser("models", help="List the models this sign-in can see")
    probe = commands.add_parser("probe", help="One vision/schema request; no game or actions executed")
    probe.add_argument("--model", required=True)
    probe.add_argument("--display-name")
    probe.add_argument("--image", required=True, help="Existing PNG screenshot")
    probe.add_argument("--think", required=True)
    args = parser.parse_args()
    if args.command == "login":
        return login()
    if args.command == "models":
        response = requests.get(API + "/models", headers={"Authorization": "Bearer " + access_token()}, timeout=30)
        response.raise_for_status()
        print(json.dumps(sorted(m["id"] for m in response.json().get("data", [])), indent=2))
        return
    from providers import XAISubscriptionProvider
    from qwen_red import SCHEMA, render_system
    png = Path(args.image).read_bytes()
    if not png.startswith(b"\x89PNG\r\n\x1a\n"):
        raise SystemExit("--image must be a PNG screenshot")
    provider = XAISubscriptionProvider(args.model)
    plan, _, usage = provider.chat(
        render_system(f"You are {args.display_name or args.model}, an AI playing Pokémon Red live on stream."),
        "Vision preflight: describe the visible scene in thought. Return actions [\"wait_60\"]. "
        "This probe will not execute any actions.",
        base64.b64encode(png).decode(), SCHEMA, args.think,
    )
    print(json.dumps({"served_model": provider.served_model, "plan": plan, "tokens": usage,
                      "execution_route": provider.route}, indent=2))


if __name__ == "__main__":
    try:
        main()
    except requests.HTTPError as exc:
        raise SystemExit(f"HTTP {exc.response.status_code if exc.response is not None else '?'}: {exc}") from None
    except (requests.RequestException, ValueError) as exc:
        raise SystemExit(str(exc)) from None
