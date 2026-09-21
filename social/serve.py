#!/usr/bin/env python3
"""Local-only review dashboard for PokeBench social drafts.

Posting is manual by design: the dashboard copies a body and opens the platform's
compose page, and Cody pastes. Nothing here holds a platform credential, so there is
nothing to leak -- but it does read and write draft files, so it binds to loopback
only and is never exposed to the LAN.
"""

import json
import mimetypes
import re
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse, unquote

ROOT = Path(__file__).resolve().parent
REPO = ROOT.parent
DRAFTS = ROOT / "drafts"
UI = ROOT / "ui"
# A draft id becomes a filename, so it may not contain a separator or a dot segment.
ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,80}$")
STATUSES = {"pending", "approved", "sent_back", "posted"}
# Only these keys may be written from the browser. Anything else in the payload is
# dropped rather than merged, so a stray field cannot rewrite run provenance.
WRITABLE = {"status", "body", "title", "note", "posted_url", "posted_at", "subreddit"}


def draft_path(draft_id):
    """Resolve an id to its file, or None if the id is not a plain filename."""
    if not ID.fullmatch(draft_id or ""):
        return None
    path = (DRAFTS / f"{draft_id}.json").resolve()
    # Belt and braces: the regex already bars separators, but re-check containment so
    # a symlinked drafts dir cannot widen the surface.
    return path if path.parent == DRAFTS.resolve() else None


def load_drafts():
    out = []
    for path in sorted(DRAFTS.glob("*.json")):
        try:
            draft = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, ValueError) as exc:
            out.append({"id": path.stem, "platform": "unknown", "status": "pending",
                        "body": "", "error": f"unreadable draft: {exc}"})
            continue
        draft.setdefault("id", path.stem)
        out.append(draft)
    return out


class Handler(BaseHTTPRequestHandler):
    server_version = "pokebench-social"

    def log_message(self, fmt, *args):
        print(f"{self.address_string()} {fmt % args}")

    def send_json(self, payload, status=200):
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def send_file(self, path, content_type=None):
        try:
            data = path.read_bytes()
        except OSError:
            return self.send_json({"error": "not found"}, 404)
        self.send_response(200)
        self.send_header("Content-Type", content_type or
                         mimetypes.guess_type(path.name)[0] or "application/octet-stream")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        route = urlparse(self.path)
        path = route.path
        if path == "/":
            return self.send_file(UI / "index.html", "text/html; charset=utf-8")
        if path == "/api/drafts":
            return self.send_json({"drafts": load_drafts(),
                                   "platforms": json.loads((ROOT / "platforms.json").read_text())})
        if path == "/api/media":
            return self.serve_media(route.query)
        if path.startswith("/ui/"):
            name = path[4:]
            # Static UI files only: no separators, so the path cannot climb out of ui/.
            if "/" in name or name.startswith("."):
                return self.send_json({"error": "bad path"}, 400)
            return self.send_file(UI / name)
        return self.send_json({"error": "not found"}, 404)

    def serve_media(self, query):
        """Serve a draft's media file. Confined to the repo, which is where run frames live."""
        raw = ""
        for part in query.split("&"):
            key, _, value = part.partition("=")
            if key == "path":
                raw = unquote(value)
        if not raw:
            return self.send_json({"error": "no path"}, 400)
        try:
            target = Path(raw).resolve(strict=True)
        except (OSError, RuntimeError):
            return self.send_json({"error": "not found"}, 404)
        # resolve() follows symlinks first, so a link pointing outside the repo is caught.
        if not target.is_relative_to(REPO) or not target.is_file():
            return self.send_json({"error": "outside repo"}, 403)
        return self.send_file(target)

    def do_POST(self):
        route = urlparse(self.path)
        if not route.path.startswith("/api/drafts/"):
            return self.send_json({"error": "not found"}, 404)
        path = draft_path(route.path[len("/api/drafts/"):])
        if path is None or not path.exists():
            return self.send_json({"error": "no such draft"}, 404)
        try:
            length = int(self.headers.get("Content-Length") or 0)
            patch = json.loads(self.rfile.read(length) or b"{}")
            if not isinstance(patch, dict):
                raise ValueError("patch must be an object")
        except (ValueError, OSError) as exc:
            return self.send_json({"error": f"bad payload: {exc}"}, 400)
        if "status" in patch and patch["status"] not in STATUSES:
            return self.send_json({"error": f"status must be one of {sorted(STATUSES)}"}, 400)

        draft = json.loads(path.read_text(encoding="utf-8"))
        draft.update({k: v for k, v in patch.items() if k in WRITABLE})
        # Write through a temp file in the same dir so a crash mid-write cannot leave a
        # half-written draft where a readable one used to be.
        tmp = path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(draft, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        tmp.replace(path)
        return self.send_json(draft)


def main():
    DRAFTS.mkdir(exist_ok=True)
    # Loopback only. This process can read the repo and rewrite drafts; nothing about it
    # should be reachable from the network.
    server = ThreadingHTTPServer(("127.0.0.1", 8787), Handler)
    print(f"PokeBench social review  ->  http://127.0.0.1:8787   ({len(load_drafts())} drafts)")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nstopped")


if __name__ == "__main__":
    main()
