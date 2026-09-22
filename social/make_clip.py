#!/usr/bin/env python3
"""Cut one turn out of a run recording into the vertical clip format.

This is the c01 "Brock falls" layout, rebuilt as something repeatable: the board's chrome
around a hole, the model's OWN plan for that turn quoted underneath, and real gameplay with
real audio in the middle. A whole-run timelapse of the per-turn frames is not the same thing
and is not worth watching -- the point is one readable moment, not 250 unreadable ones.

    python3 social/make_clip.py <RUN_ID> --turn 28 \
        --video /tmp/segment.mp4 --highlight "Charmander" --highlight "Bulbasaur"

The chrome is an HTML template rendered by headless Chromium, the same way the original was
made, so it picks up IBM Plex Mono from Google Fonts rather than needing it installed.

Finding the segment: offset = <frame mtime> - <recording start in the filename>, with the
frames on the server under runs/<run-id>/frames/turn-NNNN.png. Verify one offset against the
overlay's own TURN counter before trusting the rest -- the overlay clock and the file
position disagree by tens of seconds in both directions.
"""

import argparse
import html
import json
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
REPO = ROOT.parent

# The hole in the template, in template pixels. .shot is 1012x912 at (34, 380) with a 6px
# border and border-box sizing, so the content box a video lands in starts at (40, 386).
HOLE = (40, 386, 1000, 900)
# Where the Game Boy view sits inside a 1280x720 recording of /stream.
DEFAULT_CROP = "640:576:36:88"

TEMPLATE = """<!doctype html><html><head><meta charset="utf-8">
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=IBM+Plex+Mono:wght@400;600;700&display=swap" rel="stylesheet">
<style>
:root{--bg:#f4eed8;--card:#fbf7e8;--ink:#1e1b16;--gold:#f7d45c;--muted:#4a4539;}
*{box-sizing:border-box;margin:0;padding:0;font-family:'IBM Plex Mono',ui-monospace,monospace}
body{width:1080px;height:1920px;background:var(--bg);color:var(--ink);overflow:hidden;position:relative}
.head{position:absolute;left:40px;top:44px;width:1000px;text-align:center}
.eyebrow{display:inline-block;padding:14px 26px;background:var(--ink);color:#a9e5a0;
 font-weight:700;font-size:30px;letter-spacing:.07em;border-radius:10px}
.turn{margin-top:22px;font-weight:700;font-size:96px;letter-spacing:.02em;line-height:1}
.turn span{color:#8a8274;font-size:52px}
.model{margin-top:18px;display:inline-block;padding:12px 28px;background:var(--gold);
 border:5px solid var(--ink);border-radius:12px;box-shadow:8px 9px 0 var(--ink);
 font-weight:700;font-size:38px;letter-spacing:.04em}
.shot{position:absolute;left:34px;top:380px;width:1012px;height:912px;
 border:6px solid var(--ink);box-shadow:10px 11px 0 var(--ink);background:#ffffff;overflow:hidden}
.quote{position:absolute;left:40px;top:1330px;width:1000px;background:var(--card);
 border:6px solid var(--ink);border-radius:14px;box-shadow:10px 11px 0 var(--ink);padding:30px 34px 34px}
.qlabel{font-weight:700;font-size:25px;letter-spacing:.13em;color:var(--muted)}
.qtext{margin-top:16px;font-weight:600;font-size:__SIZE__px;line-height:1.34}
.qtext b{background:var(--gold);padding:0 6px;border-radius:4px}
.brand{position:absolute;left:40px;bottom:44px;width:1000px;text-align:center;
 font-weight:700;font-size:34px;letter-spacing:.16em;color:var(--muted)}
</style></head><body>
<div class="head">
  <div class="eyebrow">AN AI IS PLAYING POKÉMON RED</div>
  <div class="turn">TURN __TURN__ <span>/ __BUDGET__</span></div>
  <div class="model">__MODEL__</div>
</div>
<div class="shot"></div>
<div class="quote">
  <div class="qlabel">ITS PLAN THIS TURN</div>
  <div class="qtext">__QUOTE__</div>
</div>
<div class="brand">POKEBENCH.TV</div>
</body></html>"""


def turn_row(run_dir, turn):
    # A failed attempt writes its own row for the turn, with plan and result null, before the
    # retry that actually ran. Both carry the same turn number, so take the one that played.
    found = []
    for line in (run_dir / "log.jsonl").read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        if row.get("turn") == turn:
            found.append(row)
    for row in found:
        if row.get("plan"):
            return row
    if found:
        return found[-1]
    sys.exit(f"turn {turn} is not in {run_dir / 'log.jsonl'}")


def quote_html(text, highlights):
    """Escape first, then re-introduce <b> only around the phrases we were asked to mark."""
    out = html.escape(" ".join(str(text).split()))
    for phrase in highlights:
        marked = html.escape(phrase)
        out = re.sub(re.escape(marked), lambda m: f"<b>{m.group(0)}</b>", out, count=1)
    return out


def render_chrome(png, turn, budget, model, quote, size):
    chrome = next((p for p in Path("/home/cody/.cache/ms-playwright").glob("chromium-*/chrome-linux*/chrome")), None)
    if chrome is None:
        sys.exit("no headless chromium under ~/.cache/ms-playwright")
    page = (TEMPLATE.replace("__TURN__", str(turn)).replace("__BUDGET__", f"{budget:,}")
            .replace("__MODEL__", html.escape(model.upper())).replace("__QUOTE__", quote)
            .replace("__SIZE__", str(size)))
    src = png.with_suffix(".html")
    src.write_text(page, encoding="utf-8")
    # virtual-time-budget gives the webfont a chance to land; without it the render falls
    # back to a system mono and the whole thing stops looking like the board.
    subprocess.run([str(chrome), "--headless", "--disable-gpu", "--hide-scrollbars",
                    "--window-size=1080,1920", f"--screenshot={png}",
                    "--virtual-time-budget=8000", src.as_uri()],
                   check=True, capture_output=True)
    src.unlink(missing_ok=True)
    return png


def composite(chrome_png, video, out, crop):
    x, y, w, h = HOLE
    chain = (f"[1:v]crop={crop},scale={w}:{h}:flags=neighbor[game];"
             f"[0:v][game]overlay={x}:{y}:shortest=1[v]")
    cmd = ["ffmpeg", "-y", "-loglevel", "error", "-loop", "1", "-i", str(chrome_png),
           "-i", str(video), "-filter_complex", chain, "-map", "[v]", "-map", "1:a?",
           "-c:v", "libx264", "-preset", "veryfast", "-crf", "20", "-pix_fmt", "yuv420p",
           "-c:a", "aac", "-b:a", "128k", "-shortest", str(out)]
    capped = Path("/home/cody/.local/bin/capped")
    if capped.exists():
        cmd = [str(capped)] + cmd
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        sys.exit(result.stderr.strip()[:800])
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("run_id")
    ap.add_argument("--turn", type=int, required=True)
    ap.add_argument("--video", required=True, help="the already-cut gameplay segment")
    ap.add_argument("--crop", default=DEFAULT_CROP, help=f"w:h:x:y in the source (default {DEFAULT_CROP})")
    ap.add_argument("--highlight", action="append", default=[],
                    help="phrase to mark in gold; repeatable, first match only")
    ap.add_argument("--quote", help="override the plan text (default: the model's own)")
    ap.add_argument("--model", help="display name; needed while a run is still going and "
                                    "has no summary.json yet")
    ap.add_argument("--font-size", type=int, default=39)
    ap.add_argument("--out")
    args = ap.parse_args()

    run_dir = REPO / "runs" / args.run_id
    summary = json.loads((run_dir / "summary.json").read_text(encoding="utf-8")) \
        if (run_dir / "summary.json").exists() else {}
    row = turn_row(run_dir, args.turn)
    plan = args.quote or (row.get("plan") or {}).get("thought") or ""
    if not plan:
        sys.exit(f"turn {args.turn} has no plan text to quote")

    model = args.model or summary.get("display_name") or summary.get("model") or args.run_id
    budget = summary.get("budget_turns") or 1000

    out_dir = ROOT / "media" / args.run_id
    out_dir.mkdir(parents=True, exist_ok=True)
    out = Path(args.out) if args.out else out_dir / f"clip-turn-{args.turn:04d}.mp4"

    chrome_png = render_chrome(out_dir / f"chrome-turn-{args.turn:04d}.png", args.turn, budget,
                               model, quote_html(plan, args.highlight), args.font_size)
    print(f"chrome {chrome_png}")
    composite(chrome_png, args.video, out, args.crop)
    print(f"wrote  {out}")
    print(f"\n{model} / turn {args.turn}\n  \"{' '.join(plan.split())[:180]}\"")


if __name__ == "__main__":
    main()
