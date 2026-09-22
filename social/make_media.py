#!/usr/bin/env python3
"""Build the square still Instagram needs.

Instagram will not accept a text-only post, so the copy gen_drafts.py writes for it is
unpostable on its own. The still comes out of the run's own final frame -- no stock art.

    python3 social/make_media.py <RUN_ID>

Writes social/media/<RUN_ID>/square.png (1080x1080). gen_drafts.py picks it up the next
time it writes a draft for that run.

The VERTICAL video is make_clip.py's job, not this one's. A whole-run timelapse of the
per-turn frames was tried and is not worth watching: 250 unreadable stills with no turn
counter, no model name and no reasoning. One readable moment with the model's own plan
quoted under it is the format that works.
"""

import argparse
import json
import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parent
REPO = ROOT.parent

# The site's own tokens, so a post sits next to the board rather than beside it.
CANVAS = (237, 232, 214)
INK = (18, 16, 11)
GOLD = (243, 206, 82)
MUTED = (107, 102, 88)

FONTS = [
    "/usr/share/fonts/jetbrains-mono-fonts/JetBrainsMono-{w}.ttf",
    "/usr/share/fonts/liberation-mono-fonts/LiberationMono-{w}.ttf",
    "/usr/share/fonts/adobe-source-code-pro-fonts/SourceCodePro-{w}.ttf",
]


def font(size, weight="Bold"):
    for pattern in FONTS:
        path = Path(pattern.format(w=weight))
        if path.exists():
            return ImageFont.truetype(str(path), size)
    return ImageFont.load_default(size)


def wrap(draw, text, fnt, width):
    """Greedy wrap against a measured pixel width; mono fonts still vary by glyph."""
    lines, line = [], ""
    for word in text.split():
        trial = f"{line} {word}".strip()
        if draw.textlength(trial, font=fnt) <= width or not line:
            line = trial
        else:
            lines.append(line)
            line = word
    if line:
        lines.append(line)
    return lines


def headline(run):
    name = run.get("display_name") or run.get("model") or "A model"
    if run.get("termination_reason") == "beat_brock":
        return f"{name} beat Brock", f"{run['turns_used']} turns"
    label = (run.get("furthest_label") or "nowhere").lower()
    return f"{name} ran out of turns", f"as far as {label}"


def square(run, frames, out):
    """1080x1080: the last frame of the run, nearest-neighbour, over the board's canvas."""
    img = Image.new("RGB", (1080, 1080), CANVAS)
    draw = ImageDraw.Draw(img)

    shot = Image.open(frames[-1]).convert("RGB")
    # The Game Boy screen is 160x144 and the saved frames are already a whole multiple of
    # it. Scale by a whole number again or the pixels smear.
    scale = min(920 // shot.width, 620 // shot.height) or 1
    shot = shot.resize((shot.width * scale, shot.height * scale), Image.NEAREST)

    top, bottom = headline(run)
    big = font(58)
    head = wrap(draw, top, big, 980)[:2]
    # Centre the whole block rather than pinning it to the top: a short headline over a
    # small frame otherwise leaves a quarter of the canvas empty under the link.
    block = len(head) * 62 + 40 + shot.height + 230
    y = max(40, (1080 - block) // 2)

    for i, line in enumerate(head):
        draw.text((50, y + i * 62), line, font=big, fill=INK)
    y += len(head) * 62 + 40

    x = (1080 - shot.width) // 2
    draw.rectangle([x - 6, y - 6, x + shot.width + 5, y + shot.height + 5], fill=INK)
    img.paste(shot, (x, y))

    y += shot.height + 48
    draw.rectangle([50, y, 1030, y + 4], fill=GOLD)
    draw.text((50, y + 30), bottom, font=font(52), fill=INK)
    small = font(30, "Regular")
    draw.text((50, y + 104), "Same screen, 11 buttons, 1,000 turns, no hints.", font=small, fill=MUTED)
    draw.text((50, y + 148), "pokebench.tv", font=font(32), fill=INK)

    img.save(out)
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("run_id")
    args = ap.parse_args()

    run_dir = REPO / "runs" / args.run_id
    summary = run_dir / "summary.json"
    if not summary.exists():
        sys.exit(f"no summary at {summary}")
    run = json.loads(summary.read_text(encoding="utf-8"))
    frames = sorted((run_dir / "frames").glob("*.png"))
    if not frames:
        sys.exit(f"no frames under {run_dir / 'frames'} -- nothing to build from")

    out_dir = ROOT / "media" / args.run_id
    out_dir.mkdir(parents=True, exist_ok=True)
    print(f"wrote  {square(run, frames, out_dir / 'square.png')}")
    print("\nRe-run gen_drafts.py with --force to attach it to the drafts.")
    print("Vertical video: social/make_clip.py <RUN_ID> --turn N --video <segment>")


if __name__ == "__main__":
    main()
