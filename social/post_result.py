#!/usr/bin/env python3
"""Announce a finished run in the Discord #results channel.

The channel is a log: one message per run the board carries, oldest first. So a run belongs
there exactly once, and `results-posted.json` is what makes a second call a no-op rather than
a duplicate. That file is tracked, because a fresh clone that forgets what was announced would
repost the whole board.

Posting goes through a channel webhook read from outside the repo, which is public. A webhook
writes to one channel and reads nothing, so it is not the account credential the rest of the
social flow exists to avoid holding.

    python3 social/post_result.py <RUN_ID>     # announce one run
    python3 social/post_result.py --all        # announce every board run not yet announced
    python3 social/post_result.py --all -n     # show what that would post, send nothing
"""

import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent
REPO = ROOT.parent
BOARD = REPO / "site" / "runs.json"
POSTED = ROOT / "results-posted.json"
WEBHOOK = Path(os.environ.get(
    "POKEBENCH_DISCORD_RESULTS_WEBHOOK_FILE",
    Path.home() / ".config" / "pokebench" / "discord-webhook-results"))
# Discord is behind Cloudflare, which answers a default urllib User-Agent with 403 error 1010
# and says nothing about the real cause. Their API docs require a real one, so send it.
UA = "PokeBenchSocial (https://pokebench.tv, 1.0)"

WON = 0xF7D45C     # the board's gold, for a run that took the badge
RAN = 0x7F9E6C     # the board's green, for a run that used its whole budget


def board():
    """The runs the site publishes, which is the same list the channel mirrors."""
    try:
        return json.loads(BOARD.read_text(encoding="utf-8"))
    except OSError:
        sys.exit(f"{BOARD} is missing. Run: python3 site/build_runs.py")
    except ValueError as exc:
        sys.exit(f"{BOARD} is not readable JSON: {exc}")


def already_posted():
    try:
        return json.loads(POSTED.read_text(encoding="utf-8")).get("posted", {})
    except (OSError, ValueError):
        return {}


def record(run_id):
    doc = {"posted": already_posted()}
    doc["posted"][run_id] = datetime.now(timezone.utc).isoformat(timespec="seconds")
    tmp = POSTED.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(doc, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    tmp.replace(POSTED)


def money(run):
    cost = run.get("cost_usd")
    if cost is None:
        return "not recorded"
    return "free (local)" if cost == 0 else f"${cost:,.2f}"


def wall(seconds):
    seconds = int(seconds or 0)
    return f"{seconds // 3600}h {seconds % 3600 // 60:02d}m" if seconds >= 3600 else f"{seconds // 60}m"


def embed_for(run):
    budget = run.get("budget_turns") or 1000
    milestones = run.get("milestones") or []
    if run.get("beat_brock"):
        description = (f"Won the Boulder Badge on turn **{run['turns_used']}** of {budget}, "
                       "all ten milestones.")
    else:
        turn = f" on turn {milestones[-1]['turn']}" if milestones else ""
        description = (f"Ran the full {budget}-turn budget without the badge.\n"
                       f"Furthest: **{run.get('furthest_label') or 'nowhere'}**{turn} · "
                       f"{len(milestones)} of 10 milestones.")
    embed = {
        "title": run.get("display_name") or run.get("model") or run.get("run_id"),
        "description": description,
        "color": WON if run.get("beat_brock") else RAN,
        "fields": [
            {"name": "Turns", "value": f"{run['turns_used']} / {budget}", "inline": True},
            {"name": "Wall time", "value": wall(run.get("wall_time_s")), "inline": True},
            {"name": "Cost", "value": money(run), "inline": True},
        ],
        "footer": {"text": f"prompt {run.get('prompt_version')} · think {run.get('think_level')} · "
                           f"{run.get('provider')} · {run.get('run_date')}"},
    }
    # An embed title only links when there is a video; a dead title would be worse than none.
    if run.get("youtube_url"):
        embed["url"] = run["youtube_url"]
    return embed


def post(embed):
    if not WEBHOOK.exists():
        sys.exit(f"no webhook file at {WEBHOOK}")
    url = WEBHOOK.read_text(encoding="utf-8").strip()
    payload = json.dumps({"embeds": [embed], "allowed_mentions": {"parse": []}}).encode()
    req = urllib.request.Request(url + "?wait=true", data=payload, method="POST",
                                 headers={"Content-Type": "application/json", "User-Agent": UA})
    try:
        with urllib.request.urlopen(req, timeout=20) as res:
            return json.loads(res.read() or b"{}")
    except urllib.error.HTTPError as exc:
        sys.exit(f"Discord refused it: {exc.code} {exc.read().decode()[:300]}")
    except OSError as exc:
        sys.exit(f"could not reach Discord: {exc}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("run_id", nargs="?", help="omit only with --all")
    ap.add_argument("--all", action="store_true", help="every board run not already announced")
    ap.add_argument("--force", action="store_true", help="post even if it was announced before")
    ap.add_argument("-n", "--dry-run", action="store_true", help="print, send nothing")
    args = ap.parse_args()
    if not args.run_id and not args.all:
        ap.error("give a run id or --all")

    runs = board()
    done = already_posted()
    if args.run_id:
        wanted = [r for r in runs if r.get("run_id") == args.run_id]
        if not wanted:
            sys.exit(f"{args.run_id} is not on the board. It may have failed a gate in "
                     "site/build_runs.py, or the board may need rebuilding.")
    else:
        # Oldest first, so the channel keeps reading as a log rather than a stack.
        wanted = sorted(runs, key=lambda r: (r.get("run_date") or "", r.get("timestamp") or ""))

    sent = 0
    for run in wanted:
        run_id = run.get("run_id")
        if run_id in done and not args.force:
            print(f"skip   {run_id} (announced {done[run_id]})")
            continue
        embed = embed_for(run)
        if args.dry_run:
            print(f"would post  {embed['title']}: {embed['description'].splitlines()[0]}")
            continue
        post(embed)
        record(run_id)
        sent += 1
        print(f"posted {embed['title']}")
        time.sleep(1.2)  # the channel's own rate limit is the only thing pacing this
    if not args.dry_run:
        print(f"{sent} posted")


if __name__ == "__main__":
    main()
