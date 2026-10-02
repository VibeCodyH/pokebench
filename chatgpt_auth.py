"""PokéBench's own ChatGPT OAuth registration; never reads Codex credentials.

See docs/subscription-access.md. Only login needs the optional PyJWT dependency.
"""
import argparse
import base64
from contextlib import contextmanager
import fcntl
import hashlib
from http.server import BaseHTTPRequestHandler, HTTPServer
import json
import math
import os
from pathlib import Path
import re
import secrets
import tempfile
import time
from urllib.parse import parse_qs, urlencode, urlsplit
import uuid
import webbrowser

import requests

ISSUER = "https://auth.openai.com"
AUTHORIZE = ISSUER + "/api/accounts/authorize"
TOKEN = ISSUER + "/api/accounts/oauth/token"
RESOURCE = "https://api.openai.com/v1"
PLAN_SCOPE = "chatgpt.tokens.use.direct"
SCOPES = "openid profile email offline_access resource.invoke " + PLAN_SCOPE
TOKEN_FIELDS = ("access_token", "refresh_token", "id_token", "expires_at")
TERMINAL_REFRESH_ERRORS = {
    "invalid_grant", "invalid_refresh_token", "token_expired",
    "refresh_token_expired", "refresh_token_invalidated", "refresh_token_reused",
}


def auth_error(message, status=401, code="chatgpt_auth_required"):
    """Give the runner a safe HTTP-shaped error, without token-endpoint bodies."""
    response = requests.Response()
    response.status_code = status
    response._content = json.dumps({"error": {"code": code, "message": message}}).encode()
    error = requests.HTTPError(message, response=response)
    error.non_retryable = status in {400, 401, 403}
    return error


def _atomic_json(path, value):
    fd, temporary = tempfile.mkstemp(prefix=".pending-", dir=path.parent)
    try:
        with os.fdopen(fd, "w") as output:
            json.dump(value, output)
            output.flush()
            os.fsync(output.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


class Credentials:
    def __init__(self, profile=None):
        self.profile = profile or os.environ.get("POKEBENCH_CHATGPT_PROFILE", "default")
        if not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", self.profile):
            raise ValueError("ChatGPT profile must contain only letters, numbers, _ or -")
        self.directory = Path(os.environ.get(
            "POKEBENCH_CHATGPT_AUTH_DIR", "~/.config/pokebench/chatgpt"
        )).expanduser()
        self.directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.path = self.directory / (self.profile + ".json")

    @contextmanager
    def locked(self):
        # Rotating refresh tokens must not race between the probe and a runner.
        fd = os.open(self.directory / (self.profile + ".lock"), os.O_CREAT | os.O_RDWR, 0o600)
        with os.fdopen(fd, "w") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            yield

    def read(self):
        try:
            return json.loads(self.path.read_text())
        except FileNotFoundError:
            return {}

    def host_id(self):
        # One stable ID per runtime, shared by its named account registrations.
        path = self.directory / "host.json"
        fd = os.open(self.directory / "host.lock", os.O_CREAT | os.O_RDWR, 0o600)
        with os.fdopen(fd, "w") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            if not path.exists():
                _atomic_json(path, {"id": "urn:uuid:" + str(uuid.uuid4())})
            return json.loads(path.read_text())["id"]

    def save_tokens(self, body, previous, identity=None):
        record = dict(previous)
        if identity is not None:
            if previous.get("subject") and previous["subject"] != identity["sub"]:
                raise auth_error("This profile belongs to another account; use a new --profile")
            record.update(subject=identity["sub"], email=identity.get("email"), issuer=ISSUER)
        for field in ("access_token", "refresh_token"):
            if not isinstance(body.get(field), str) or not body[field]:
                raise auth_error("OAuth returned an incomplete token set")
            record[field] = body[field]
        expires = body.get("expires_in")
        if type(expires) not in (int, float) or not math.isfinite(expires) or expires <= 0:
            raise auth_error("OAuth returned an invalid token lifetime")
        if body.get("token_type", "").lower() != "bearer":
            raise auth_error("OAuth returned an unsupported token type")
        if body.get("id_token"):
            record["id_token"] = body["id_token"]
        # A fresh sign-in must explicitly grant plan access. Only refresh may retain scopes.
        record["scopes"] = (body["scope"].split() if "scope" in body
                            else [] if identity is not None else previous.get("scopes", []))
        record["expires_at"] = time.time() + expires
        _atomic_json(self.path, record)
        return record

    def access_token(self):
        with self.locked():
            record = self.read()
            if PLAN_SCOPE not in record.get("scopes", []):
                raise auth_error("ChatGPT plan access is not enabled; run chatgpt_auth.py login")
            if not record.get("access_token") or not record.get("client_id"):
                raise auth_error("Sign in first with chatgpt_auth.py login")
            if time.time() < record.get("expires_at", 0) - 60:
                return record["access_token"]
            if not record.get("refresh_token"):
                raise auth_error("ChatGPT session expired; sign in again")
            response = requests.post(TOKEN, data={
                "grant_type": "refresh_token", "client_id": record["client_id"],
                "refresh_token": record["refresh_token"], "resource": RESOURCE,
            }, timeout=30)
            body = _token_body(response)
            if not response.ok:
                code = body.get("error")
                if isinstance(code, dict):
                    code = code.get("code")
                if code in TERMINAL_REFRESH_ERRORS:
                    for field in TOKEN_FIELDS:
                        record.pop(field, None)
                    _atomic_json(self.path, record)
                    raise auth_error("ChatGPT session ended; sign in again", code=code)
                raise auth_error("ChatGPT token refresh failed", response.status_code,
                                 code if isinstance(code, str) else "oauth_refresh_failed")
            # Refresh keeps the original account/client binding; never switch profiles here.
            record = self.save_tokens(body, record)
            if PLAN_SCOPE not in record["scopes"]:
                raise auth_error("ChatGPT plan permission was removed; sign in again")
            return record["access_token"]


def _token_body(response):
    try:
        body = response.json()
    except ValueError:
        raise auth_error("OAuth endpoint returned a non-JSON response", response.status_code) from None
    if not isinstance(body, dict):
        raise auth_error("OAuth endpoint returned an invalid response", response.status_code)
    return body


def validate_identity(token, client_id, nonce):
    import jwt
    key = jwt.PyJWKClient(ISSUER + "/.well-known/jwks.json", timeout=30).get_signing_key_from_jwt(token)
    claims = jwt.decode(token, key.key, algorithms=["RS256"], audience=client_id,
                        issuer=ISSUER, options={"require": ["exp", "iss", "aud", "sub", "nonce"]})
    if not secrets.compare_digest(str(claims["nonce"]), nonce):
        raise auth_error("OAuth nonce did not match")
    if claims.get("azp", client_id) != client_id:
        raise auth_error("OAuth authorized party did not match")
    return claims


def finish_login(credentials, previous, query, state, nonce, verifier, redirect_uri):
    if not secrets.compare_digest(query.get("state", ""), state):
        raise auth_error("OAuth state did not match")
    if query.get("error"):
        raise auth_error("ChatGPT sign-in was declined or unavailable")
    client_id = query.get("client_id") or previous.get("client_id")
    if not client_id or client_id == "dynamic_agent_client":
        raise auth_error("OAuth registration did not return an issued client ID")
    if previous.get("client_id") and client_id != previous["client_id"]:
        raise auth_error("OAuth returned another registration; existing profile was preserved")
    if not query.get("code"):
        raise auth_error("OAuth callback did not contain an authorization code")
    response = requests.post(TOKEN, data={
        "grant_type": "authorization_code", "client_id": client_id,
        "code": query["code"], "code_verifier": verifier,
        "redirect_uri": redirect_uri, "resource": RESOURCE,
    }, timeout=30)
    if not response.ok:
        raise auth_error("OAuth code exchange failed; start sign-in again", response.status_code)
    body = _token_body(response)
    identity = validate_identity(body.get("id_token", ""), client_id, nonce)
    previous = dict(previous, client_id=client_id, ext_agent_host_id=credentials.host_id())
    record = credentials.save_tokens(body, previous, identity)
    if PLAN_SCOPE not in record["scopes"]:
        raise auth_error("Signed in, but ChatGPT plan usage was not authorized")


def login(credentials, port=1455, no_browser=False):
    # Fail before the browser opens when the optional verifier is not installed.
    import jwt  # noqa: F401
    with credentials.locked():
        previous = credentials.read()
        state, nonce, verifier = (secrets.token_urlsafe(32) for _ in range(3))
        result = {}

        class Callback(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass  # The request URL contains the authorization code.

            def do_GET(self):
                parts = urlsplit(self.path)
                query = parse_qs(parts.query)
                valid = (parts.path == "/auth/callback"
                         and all(len(values) == 1 for values in query.values())
                         and secrets.compare_digest(query.get("state", [""])[0], state))
                self.send_response(200 if valid else 400)
                self.send_header("Content-Type", "text/plain; charset=utf-8")
                self.send_header("Cache-Control", "no-store")
                self.end_headers()
                self.wfile.write(b"Return to the Pokebench terminal to finish sign-in." if valid
                                 else b"Invalid OAuth callback.")
                if valid:
                    result.update({key: values[0] for key, values in query.items()})

        with HTTPServer(("127.0.0.1", port), Callback) as server:
            server.timeout = 1
            redirect = f"http://127.0.0.1:{server.server_port}/auth/callback"
            params = {
                "client_id": previous.get("client_id", "dynamic_agent_client"),
                "ext_agent_host_id": credentials.host_id(), "response_type": "code",
                "redirect_uri": redirect, "scope": SCOPES, "resource": RESOURCE,
                "state": state, "nonce": nonce, "code_challenge_method": "S256",
                "code_challenge": base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode(),
            }
            if not previous.get("client_id"):
                params["agent_name_hint"] = "Pokebench"
            # No ID-token hint: the displayed URL must never contain a saved credential.
            url = AUTHORIZE + "?" + urlencode(params)
            print(f"Continue with ChatGPT (profile: {credentials.profile})\n{url}", flush=True)
            if not no_browser:
                webbrowser.open(url)
            deadline = time.monotonic() + 300
            while not result and time.monotonic() < deadline:
                server.handle_request()
            if not result:
                raise auth_error("Sign-in timed out; run login again")
            finish_login(credentials, previous, result, state, nonce, verifier, redirect)
        print(f"ChatGPT plan access saved for profile {credentials.profile}.")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--profile", default=None, help="Separate named account/workspace registration")
    commands = parser.add_subparsers(dest="command", required=True)
    signin = commands.add_parser("login")
    signin.add_argument("--port", type=int, default=1455)
    signin.add_argument("--no-browser", action="store_true")
    commands.add_parser("models", help="List this account's current model catalog")
    probe = commands.add_parser("probe", help="One vision/schema request; no game or actions executed")
    probe.add_argument("--model", required=True)
    probe.add_argument("--display-name", help="Use the same identity sentence as the scored model row")
    probe.add_argument("--image", required=True, help="Existing PNG screenshot")
    probe.add_argument("--think", required=True, help="Effort supported by the selected model")
    args = parser.parse_args()
    credentials = Credentials(args.profile)
    if args.command == "login":
        login(credentials, args.port, args.no_browser)
    elif args.command == "models":
        response = requests.get(RESOURCE + "/models", headers={
            "Authorization": "Bearer " + credentials.access_token(),
        }, timeout=30)
        response.raise_for_status()
        body = response.json()
        if not isinstance(body.get("models"), list):
            raise ValueError("ChatGPT model catalog returned an unexpected shape")
        print(json.dumps([{"id": m["slug"], "name": m.get("display_name")}
                          for m in body["models"] if m.get("visibility") == "list"], indent=2))
    else:
        from chatgpt_provider import ChatGPTProvider
        from qwen_red import SCHEMA, render_system
        provider = ChatGPTProvider(args.model, profile=credentials.profile)
        png = Path(args.image).read_bytes()
        if not png.startswith(b"\x89PNG\r\n\x1a\n"):
            raise ValueError("--image must be a PNG screenshot")
        plan, _, usage = provider.chat(
            render_system(f"You are {args.display_name or args.model}, an AI playing Pokémon Red live on stream."),
            "Vision preflight: describe the visible scene in thought. Return actions [\"wait_60\"]. "
            "This probe will not execute any actions.",
            base64.b64encode(png).decode(), SCHEMA, args.think,
        )
        print(json.dumps({"served_model": provider.served_model, "plan": plan,
                          "tokens": usage, "execution_route": provider.route}, indent=2))


if __name__ == "__main__":
    try:
        main()
    except (requests.RequestException, ValueError) as exc:
        raise SystemExit(str(exc)) from None
