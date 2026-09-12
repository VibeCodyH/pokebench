#!/usr/bin/env python3
"""Build the static leaderboard from runs/*/summary.json."""

import json
from pathlib import Path
import re
import sys

# Ranking floor. Prompt v19 (9c5a845) dropped the map reachability flood-fill, the last harness
# feature that did spatial reasoning FOR the model; v17 had already removed prompt coaching.
# Runs before v19 scored a different game and cannot sit on the same board.
HARNESS_FLOOR = 19


def prompt_number(run):
    match = re.fullmatch(r"v(\d+)", str(run.get("prompt_version") or ""))
    return int(match.group(1)) if match else None


def main():
    root = Path(__file__).resolve().parent.parent
    runs = []
    legacy = 0
    for path in sorted(root.glob("runs/*/summary.json")):
        try:
            run = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(run, dict):
                raise ValueError("summary must be a JSON object")
            for field in ("furthest_index", "turns_used"):
                if type(run.get(field)) not in (int, float):
                    raise ValueError(f"{field} must be a number")
            # Reject non-finite numbers, which are not valid JSON.
            json.dumps(run, allow_nan=False)
        except (OSError, UnicodeError, ValueError) as exc:
            print(f"Warning: skipping {path.relative_to(root)}: {exc}", file=sys.stderr)
            continue
        version = prompt_number(run)
        if version is None or version < HARNESS_FLOOR:
            legacy += 1
            continue
        runs.append(run)

    def furthest_turn(run):
        # Spec tiebreaker: same furthest milestone -> fewer turns to REACH it. Non-winners all
        # run to budget, so turns_used ties them all; the furthest milestone's first-hit turn
        # is the real discriminator. Falls back to turns_used when no milestone was reached.
        key = run.get("furthest_key")
        for milestone in run.get("milestones") or []:
            if milestone.get("key") == key and type(milestone.get("turn")) in (int, float):
                return milestone["turn"]
        return run["turns_used"]

    runs.sort(key=lambda run: (-run["furthest_index"], furthest_turn(run)))
    output = root / "site" / "runs.json"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(runs, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    print(f"Aggregated {len(runs)} runs into site/runs.json "
          f"({legacy} legacy runs below prompt v{HARNESS_FLOOR} excluded)")


if __name__ == "__main__":
    main()
