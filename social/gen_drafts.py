#!/usr/bin/env python3
"""Draft one social post per platform from a finished run's summary.json.

Every number a draft states is read out of the summary or computed from the same
board `build_runs.py` publishes. Nothing is estimated and nothing is invented: a
draft that cannot be backed by the receipts is not written at all.

    python3 social/gen_drafts.py <RUN_ID> [--platforms x,bluesky] [--force]
"""

import argparse
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent
REPO = ROOT.parent
sys.path.insert(0, str(REPO / "site"))
import build_runs  # noqa: E402  -- reuse the board's own eligibility gates

SITE = "https://pokebench.tv"


def board():
    """The runs build_runs.py would publish, in its ranking order."""
    runs = []
    for path in sorted((REPO / "runs").glob("*/summary.json")):
        try:
            run = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, ValueError):
            continue
        version = build_runs.prompt_number(run)
        if version is None or version < build_runs.HARNESS_FLOOR:
            continue
        if not build_runs.finished(run):
            continue
        runs.append(run)
    return runs


def furthest_turn(run):
    for m in run.get("milestones") or []:
        if m.get("key") == run.get("furthest_key") and isinstance(m.get("turn"), (int, float)):
            return m["turn"]
    return run["turns_used"]


def duration(seconds):
    if not isinstance(seconds, (int, float)) or seconds < 0:
        return None
    h, m = int(seconds // 3600), int(seconds % 3600 // 60)
    return f"{h}h {m}m" if h else f"{m}m"


def money(value):
    if not isinstance(value, (int, float)):
        return None
    return "free (local)" if value == 0 else f"${value:,.2f}"


def facts(run, runs):
    """Everything a draft is allowed to assert, derived only from the receipts."""
    ranked = sorted(runs, key=lambda r: (-r["furthest_index"], furthest_turn(r)))
    rank = next(i for i, r in enumerate(ranked, 1) if r["run_id"] == run["run_id"])
    winners = [r for r in ranked if r.get("beat_brock")]
    # "Record" means: won, and no other winner reached the win in fewer turns.
    better = [r for r in winners if r["run_id"] != run["run_id"]
              and furthest_turn(r) < furthest_turn(run)]
    return {
        "name": run.get("display_name") or run["model"],
        "rank": rank,
        "total": len(ranked),
        "won": bool(run.get("beat_brock")),
        "record": bool(run.get("beat_brock")) and not better,
        "turns": run["turns_used"],
        "budget": run.get("budget_turns"),
        "milestone": run.get("furthest_label"),
        "wall": duration(run.get("wall_time_s")),
        "cost": money(run.get("cost_usd")),
        "local": "ollama" in str(run.get("provider", "")).lower(),
        "winners": len(winners),
        "runner_up": min((furthest_turn(r) for r in winners
                          if r["run_id"] != run["run_id"]), default=None),
        "youtube": run.get("youtube_url") or "",
        "date": run.get("run_date", ""),
    }


def headline(f):
    """One sentence stating what happened. Bad results get stated, not spun."""
    if f["record"]:
        line = f"{f['name']} beat Brock in {f['turns']} turns, a new PokeBench best."
        if f["runner_up"]:
            line += f" The previous best was {f['runner_up']}."
        return line
    if f["won"]:
        return f"{f['name']} beat Brock in {f['turns']} turns."
    return (f"{f['name']} ran out of budget at {f['turns']} turns. "
            f"Furthest it got: {f['milestone']}.")


def receipts(f):
    bits = [f"Rank {f['rank']} of {f['total']}"]
    if f["wall"]:
        bits.append(f"{f['wall']} of wall time")
    if f["cost"]:
        bits.append(f["cost"])
    return " · ".join(bits)


def build(run, f, platform):
    """Return the draft fields for one platform, or None if it has nothing to say."""
    link = f["youtube"] or SITE
    if platform == "x":
        return {"body": f"{headline(f)}\n\n{receipts(f)}\n\n{link}"}
    if platform == "bluesky":
        return {"body": f"{headline(f)}\n\n{receipts(f)}\n\n{link}"}
    if platform == "discord":
        return {"body": f"**{headline(f)}**\n\n{receipts(f)}\n{link}"}
    if platform == "reddit":
        # The title already carries the headline; repeating it as the first body line
        # reads like a bot. The body opens on the numbers instead.
        title = headline(f).rstrip(".")
        body = (f"- Furthest milestone: {f['milestone']}\n"
                f"- Turns used: {f['turns']} of {f['budget']}\n"
                + (f"- Wall time: {f['wall']}\n" if f["wall"] else "")
                + (f"- Cost: {f['cost']}\n" if f["cost"] else "")
                + f"\nEvery run is scored on the same 10-milestone ladder with the same prompt. "
                  f"Full turn logs and the leaderboard: {SITE}")
        return {"title": title[:300], "body": body, "subreddit": "LocalLLaMA"}
    if platform == "instagram":
        return {"body": f"{headline(f)}\n\n{receipts(f)}\n\nLeaderboard at pokebench.tv"}
    if platform == "tiktok":
        return {"body": f"{headline(f)} {receipts(f)} #pokebench #ai"}
    return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("run_id")
    ap.add_argument("--platforms", default="x,bluesky,reddit,discord")
    ap.add_argument("--force", action="store_true", help="overwrite existing drafts for this run")
    args = ap.parse_args()

    summary = REPO / "runs" / args.run_id / "summary.json"
    if not summary.exists():
        sys.exit(f"no summary at {summary}")
    run = json.loads(summary.read_text(encoding="utf-8"))

    runs = board()
    if not any(r["run_id"] == run["run_id"] for r in runs):
        sys.exit(f"{args.run_id} is not on the board (legacy prompt or unfinished) -- "
                 "it would not be published, so it gets no posts.")

    known = json.loads((ROOT / "platforms.json").read_text())
    wanted = [p.strip() for p in args.platforms.split(",") if p.strip()]
    unknown = [p for p in wanted if p not in known]
    if unknown:
        sys.exit(f"unknown platforms: {', '.join(unknown)}. Known: {', '.join(known)}")

    f = facts(run, runs)
    drafts_dir = ROOT / "drafts"
    drafts_dir.mkdir(exist_ok=True)
    slug = re.sub(r"[^a-z0-9]+", "-", (f["name"] or "run").lower()).strip("-")
    written = []
    for platform in wanted:
        fields = build(run, f, platform)
        if not fields:
            continue
        draft_id = f"{f['date']}-{slug}-{platform}"
        path = drafts_dir / f"{draft_id}.json"
        if path.exists() and not args.force:
            print(f"skip   {draft_id} (exists; --force to overwrite)")
            continue
        draft = {
            "id": draft_id,
            "platform": platform,
            "kind": "run recap",
            "run_id": run["run_id"],
            "status": "pending",
            "title": fields.get("title", ""),
            "body": fields["body"],
            "subreddit": fields.get("subreddit", ""),
            "link": f["youtube"] or SITE,
            "media": [],
            "facts": {k: f[k] for k in ("rank", "total", "turns", "won", "record", "cost", "wall")},
            "created": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "note": "",
            "posted_url": "",
            "posted_at": "",
        }
        path.write_text(json.dumps(draft, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        written.append(draft_id)
        print(f"wrote  {draft_id}")

    print(f"\n{len(written)} draft(s) for {f['name']} -- "
          f"rank {f['rank']}/{f['total']}, {f['turns']} turns, {f['cost'] or 'cost unknown'}")
    if written:
        print("Review at http://127.0.0.1:8787 (python3 social/serve.py)")


if __name__ == "__main__":
    main()
