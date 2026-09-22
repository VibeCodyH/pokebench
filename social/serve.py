#!/usr/bin/env python3
"""Local-only review dashboard for PokeBench social drafts.

Posting is manual by design: the dashboard copies a body and opens the platform's
compose page, and Cody pastes. Discord is the exception and posts directly, through a
channel webhook read from outside the repo -- a webhook writes to one channel and reads
nothing, so it is not the account credential this flow exists to avoid holding. The
server reads and writes draft files, so it binds to loopback only and is never exposed
to the LAN.
"""

import json
import mimetypes
import os
import re
import urllib.error
import urllib.request
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse, unquote

ROOT = Path(__file__).resolve().parent
REPO = ROOT.parent
DRAFTS = ROOT / "drafts"
UI = ROOT / "ui"
SCHEDULE = ROOT / "schedule.json"
BOARD = REPO / "site" / "runs.json"
# A draft id becomes a filename, so it may not contain a separator or a dot segment.
ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,80}$")
STATUSES = {"pending", "approved", "sent_back", "posted"}
# Only these keys may be written from the browser. Anything else in the payload is
# dropped rather than merged, so a stray field cannot rewrite run provenance.
WRITABLE = {"status", "body", "title", "note", "posted_url", "posted_at", "subreddit", "post_on"}
# The schedule is a separate store with a separate allowlist. Sharing WRITABLE would let a
# draft PATCH reach schedule keys and vice versa.
SCHEDULE_WRITABLE = {"date", "status", "note", "youtube_url"}
SCHEDULE_STATUSES = {"planned", "published"}
DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
# Discord is the one platform that can be posted from here, because a channel webhook is a
# URL rather than an account credential: it can write to exactly one channel and read nothing.
# Every other platform stays copy-and-paste. The URL lives outside the repo, which is public.
DISCORD_WEBHOOK = Path(os.environ.get(
    "POKEBENCH_DISCORD_WEBHOOK_FILE",
    Path.home() / ".config" / "pokebench" / "discord-webhook-announcements"))
# Discord sits behind Cloudflare, which answers a default urllib User-Agent with 403 error 1010
# rather than anything about the request. Their API docs require a real one, so send it.
DISCORD_UA = "PokeBenchSocial (https://pokebench.tv, 1.0)"


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


def load_schedule():
    """Read the schedule, tolerating a missing file so a fresh clone still serves."""
    try:
        doc = json.loads(SCHEDULE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {"source": "", "entries": []}
    doc.setdefault("entries", [])
    return doc


def save_schedule(doc):
    tmp = SCHEDULE.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(doc, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    tmp.replace(SCHEDULE)


def board_runs():
    """Runs the site publishes, so a run can be scheduled without typing its id."""
    try:
        return json.loads(BOARD.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []


def schedule_payload():
    doc = load_schedule()
    scheduled = {e.get("run_id") for e in doc["entries"]}
    unscheduled = [{"run_id": r.get("run_id"), "display_name": r.get("display_name"),
                    "turns_used": r.get("turns_used"),
                    "termination_reason": r.get("termination_reason"),
                    "youtube_url": r.get("youtube_url") or ""}
                   for r in board_runs() if r.get("run_id") not in scheduled]
    return {"source": doc.get("source", ""), "entries": doc["entries"], "unscheduled": unscheduled}


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
        if path == "/api/schedule":
            return self.send_json(schedule_payload())
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

    def read_patch(self):
        """Body as a dict, or None after an error response has already been sent."""
        try:
            length = int(self.headers.get("Content-Length") or 0)
            patch = json.loads(self.rfile.read(length) or b"{}")
            if not isinstance(patch, dict):
                raise ValueError("patch must be an object")
            return patch
        except (ValueError, OSError) as exc:
            self.send_json({"error": f"bad payload: {exc}"}, 400)
            return None

    def do_POST(self):
        route = urlparse(self.path)
        if route.path.startswith("/api/schedule/"):
            return self.post_schedule(route.path[len("/api/schedule/"):])
        if route.path.startswith("/api/drafts/") and route.path.endswith("/publish"):
            return self.publish_draft(route.path[len("/api/drafts/"):-len("/publish")])
        if not route.path.startswith("/api/drafts/"):
            return self.send_json({"error": "not found"}, 404)
        path = draft_path(route.path[len("/api/drafts/"):])
        if path is None or not path.exists():
            return self.send_json({"error": "no such draft"}, 404)
        patch = self.read_patch()
        if patch is None:
            return
        if "status" in patch and patch["status"] not in STATUSES:
            return self.send_json({"error": f"status must be one of {sorted(STATUSES)}"}, 400)
        # An empty post_on is allowed: it drops the draft back to the undated pile.
        if patch.get("post_on") and not DATE.fullmatch(str(patch["post_on"])):
            return self.send_json({"error": "post_on must be YYYY-MM-DD"}, 400)

        draft = json.loads(path.read_text(encoding="utf-8"))
        draft.update({k: v for k, v in patch.items() if k in WRITABLE})
        # Write through a temp file in the same dir so a crash mid-write cannot leave a
        # half-written draft where a readable one used to be.
        tmp = path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(draft, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        tmp.replace(path)
        return self.send_json(draft)

    def publish_draft(self, draft_id):
        """Send a Discord draft to the channel webhook and record where it landed.

        This is the one platform the dashboard posts to directly. A webhook writes to a
        single channel and can read nothing, so it is not the account credential the rest
        of the manual flow exists to avoid holding.
        """
        path = draft_path(draft_id)
        if path is None or not path.exists():
            return self.send_json({"error": "no such draft"}, 404)
        draft = json.loads(path.read_text(encoding="utf-8"))
        platform = draft.get("platform")
        if platform != "discord":
            return self.send_json({"error": f"nothing posts to {platform} from here, copy and paste it"}, 400)
        if draft.get("status") == "posted":
            return self.send_json({"error": "already posted"}, 409)
        if draft.get("media"):
            return self.send_json({"error": "file upload is not wired yet, post this one by hand"}, 400)
        body = (draft.get("body") or "").strip()
        if not body:
            return self.send_json({"error": "draft has no body"}, 400)
        if len(body) > 2000:
            return self.send_json({"error": f"Discord caps a message at 2000, this is {len(body)}"}, 400)
        if not DISCORD_WEBHOOK.exists():
            return self.send_json({"error": f"no webhook file at {DISCORD_WEBHOOK}"}, 400)
        hook = DISCORD_WEBHOOK.read_text().strip()

        try:
            # parse:[] so an @everyone that survived review cannot ping the server on the way out.
            payload = json.dumps({"content": body, "allowed_mentions": {"parse": []}}).encode()
            req = urllib.request.Request(hook + "?wait=true", data=payload, method="POST",
                                         headers={"Content-Type": "application/json",
                                                  "User-Agent": DISCORD_UA})
            with urllib.request.urlopen(req, timeout=20) as res:
                sent = json.loads(res.read() or b"{}")
            # The send response carries the channel but not the guild, and a message link needs both.
            meta_req = urllib.request.Request(hook, headers={"User-Agent": DISCORD_UA})
            with urllib.request.urlopen(meta_req, timeout=20) as res:
                meta = json.loads(res.read() or b"{}")
        except urllib.error.HTTPError as exc:
            return self.send_json({"error": f"Discord refused it: {exc.code} {exc.read().decode()[:300]}"}, 502)
        except OSError as exc:
            return self.send_json({"error": f"could not reach Discord: {exc}"}, 502)

        guild, channel, message = meta.get("guild_id"), sent.get("channel_id"), sent.get("id")
        link = f"https://discord.com/channels/{guild}/{channel}/{message}" if guild and channel else ""
        draft.update({"status": "posted", "posted_url": link,
                      "posted_at": datetime.now(timezone.utc).isoformat()})
        tmp = path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(draft, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        tmp.replace(path)
        return self.send_json(draft)

    def post_schedule(self, run_id):
        """Create or update one run's release date.

        The whole point of the feature is the conflict check: on 2026-09-18 five videos went
        out in one day and four of them drew 1 view or fewer, and on 2026-09-20 a genuine
        Brock win published alongside the record-setter and drew 3. So a PLANNED date that
        another entry already occupies is refused here, in the server, rather than warned
        about in the UI where it can be clicked past.

        Published entries are exempt. They are a record of what happened, and the seeded
        history breaks the rule five times over -- validating it would make the file
        unloadable rather than make the past any different.
        """
        if not ID.fullmatch(run_id or ""):
            return self.send_json({"error": "bad run id"}, 400)
        patch = self.read_patch()
        if patch is None:
            return
        status = patch.get("status", "planned")
        if status not in SCHEDULE_STATUSES:
            return self.send_json({"error": f"status must be one of {sorted(SCHEDULE_STATUSES)}"}, 400)
        date = (patch.get("date") or "").strip()
        if date and not DATE.fullmatch(date):
            return self.send_json({"error": "date must be YYYY-MM-DD"}, 400)

        doc = load_schedule()
        entries = doc["entries"]
        existing = next((e for e in entries if e.get("run_id") == run_id), None)

        # An empty date drops a planned entry. A published one stays: clearing the date of
        # something already on YouTube would silently delete history.
        if not date:
            if existing and existing.get("status") == "published":
                return self.send_json({"error": "published entries keep their date"}, 409)
            doc["entries"] = [e for e in entries if e.get("run_id") != run_id]
            save_schedule(doc)
            return self.send_json(schedule_payload())

        if status == "planned":
            clash = next((e for e in entries
                          if e.get("date") == date and e.get("run_id") != run_id), None)
            if clash:
                return self.send_json(
                    {"error": f"{date} already has a video: {clash.get('display_name') or clash.get('run_id')}",
                     "conflict_with": clash.get("run_id")}, 409)

        if existing is None:
            run = next((r for r in board_runs() if r.get("run_id") == run_id), {})
            existing = {"run_id": run_id, "display_name": run.get("display_name") or run_id,
                        "date": "", "status": "planned", "youtube_url": "", "note": ""}
            entries.append(existing)
        existing.update({k: v for k, v in patch.items() if k in SCHEDULE_WRITABLE})
        existing["date"] = date
        existing["status"] = status
        doc["entries"] = sorted(entries, key=lambda e: (e.get("date") or "", e.get("display_name") or ""))
        save_schedule(doc)
        return self.send_json(schedule_payload())


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
