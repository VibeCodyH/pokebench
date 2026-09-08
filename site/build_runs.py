#!/usr/bin/env python3
"""Build the static leaderboard from runs/*/summary.json."""

import json
from pathlib import Path
import sys


def main():
    root = Path(__file__).resolve().parent.parent
    runs = []
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
        runs.append(run)

    runs.sort(key=lambda run: (-run["furthest_index"], run["turns_used"]))
    output = root / "site" / "runs.json"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(runs, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    print(f"Aggregated {len(runs)} runs into site/runs.json")


if __name__ == "__main__":
    main()
