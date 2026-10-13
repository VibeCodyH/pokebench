"""PokéBench xAI subscription sign-in PROBE (SuperGrok / X Premium+ / X Subscription plans).

Answers one question before any harness wiring: does this account's plan serve Grok over
xAI's OAuth API access? xAI has no dynamic client registration (auth.x.ai's discovery document
lists no registration_endpoint), so this uses the shared Grok CLI public client that Hermes
Agent and OpenClaw also use; the consent screen will name Grok Build. Device-code flow
(RFC 8628), no local callback. Tokens stay outside the repo.

    python3 xai_auth.py login
    python3 xai_auth.py models
    python3 xai_auth.py probe --model grok-4.7 --image frame.png --think high
"""
import argparse
import base64
import json
import os
from pathlib import Path
import time

import requests

from chatgpt_auth import _atomic_json

ISSUER = "https://auth.x.ai"
DEVICE_CODE = ISSUER + "/oauth2/device/code"
TOKEN = ISSUER + "/oauth2/token"
CLIENT_ID = "b1a00492-073a-47ea-816f-4c329264a828"   # shared Grok CLI public client
SCOPES = "openid profile email offline_access grok-cli:access api:access"
API = "https://api.x.ai/v1"
DEVICE_GRANT = "urn:ietf:params:oauth:grant-type:device_code"
REFRESH_EARLY_S = 3600   # access tokens live ~6h


def token_path():
    directory = Path(os.environ.get("POKEBENCH_XAI_AUTH_DIR", "~/.config/pokebench/xai")).expanduser()
    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    return directory / "default.json"


def save(body, previous=None):
    if not body.get("access_token") or str(body.get("token_type", "")).lower() != "bearer":
        raise ValueError("xAI returned an incomplete token set")
    record = dict(previous or {})
    record.update(access_token=body["access_token"],
                  refresh_token=body.get("refresh_token") or record.get("refresh_token"),
                  scopes=body.get("scope", record.get("scopes", "")),
                  expires_at=time.time() + float(body.get("expires_in", 0)))
    _atomic_json(token_path(), record)
    return record


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
            record = save(body)
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


def access_token():
    record = json.loads(token_path().read_text()) if token_path().exists() else {}
    if not record.get("access_token"):
        raise SystemExit("Sign in first: python3 xai_auth.py login")
    if time.time() < record.get("expires_at", 0) - REFRESH_EARLY_S:
        return record["access_token"]
    response = requests.post(TOKEN, data={"grant_type": "refresh_token", "client_id": CLIENT_ID,
                                          "refresh_token": record.get("refresh_token", "")},
                             headers={"Accept": "application/json"}, timeout=30)
    if not response.ok:
        raise SystemExit(f"Token refresh failed: HTTP {response.status_code}; run login again")
    return save(response.json(), record)["access_token"]


def report_http(exc):
    response = exc.response
    detail = ""
    try:
        error = response.json().get("error", response.json())
        detail = error.get("message", error) if isinstance(error, dict) else error
    except (ValueError, AttributeError):
        detail = response.text[:300]
    raise SystemExit(f"HTTP {response.status_code}: {detail}")


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
    token = access_token()
    try:
        if args.command == "models":
            response = requests.get(API + "/models", headers={"Authorization": "Bearer " + token}, timeout=30)
            response.raise_for_status()
            print(json.dumps(sorted(m["id"] for m in response.json().get("data", [])), indent=2))
            return
        # The probe goes through the same provider class a scored xAI run uses, with the
        # OAuth bearer in place of an API key (set for this process only, never written).
        os.environ["XAI_API_KEY"] = token
        from providers import XAIProvider
        from qwen_red import SCHEMA, render_system
        png = Path(args.image).read_bytes()
        if not png.startswith(b"\x89PNG\r\n\x1a\n"):
            raise SystemExit("--image must be a PNG screenshot")
        provider = XAIProvider(args.model)
        result = provider.chat(
            render_system(f"You are {args.display_name or args.model}, an AI playing Pokémon Red live on stream."),
            "Vision preflight: describe the visible scene in thought. Return actions [\"wait_60\"]. "
            "This probe will not execute any actions.",
            base64.b64encode(png).decode(), SCHEMA, args.think,
        )
        print(json.dumps({"served_model": getattr(provider, "served_model", None), "result": result},
                         indent=2, default=str))
    except requests.HTTPError as exc:
        report_http(exc)


if __name__ == "__main__":
    main()
