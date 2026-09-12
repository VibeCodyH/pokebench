# What a run writes to disk

Every run gets its own directory, `runs/<model>-<timestamp>-<id>/`. Runs are append-only: once
recorded, nothing in here is rewritten. `summary.json` and `log.jsonl` are the receipts the
leaderboard and any audit read from; the PNGs are a convenience and are gitignored.

| Path | What it is |
|---|---|
| `summary.json` | The score. Milestones with the turn each first fired, turns used, tokens, wall time, cost, prompt SHA, harness SHA, execution route |
| `log.jsonl` | One record per turn (below) |
| `frames/turn-0001.png` | The exact PNG the model saw that turn, four-digit turn number. `--no-frames` skips these. `qwen_red.py` names these `turn_0001.png` and writes the full-size frame instead of the resized one it sent |
| `frames/turn-0001-error-<timestamp>.png` | A failed attempt's own image, kept separately so a retry cannot overwrite the frame that caused it |
| `notes.md` | The model's own running notes, cleared per game and labeled unverified in the prompt |

Two receipts predate the one history rewrite this repo has had, so their `harness_git_sha`
names a commit that is no longer reachable. [docs/sha-rewrite-map.md](sha-rewrite-map.md) maps
those two SHAs to the commits they became.

## The per-turn record

Each `log.jsonl` line carries what the model saw, what it decided, and what actually happened:

- `frame_file` — path to the PNG relative to the run directory, or null when `--no-frames` is set
- `collision` and `warps` — raw, straight from the memory reader, not summarized
- `party_count`, and the snapshot's `dialog_open`, `menu_open`, `in_battle`
- `settle` — `cleared` if the screen finished its transition before the state was read, `capped` if it
  ran out of time. A `capped` turn means the model may have been looking at a half-drawn frame
- the rendered user message, the model's thinking and plan, the per-action before/after position and
  map, and the raw response body on a parse failure

## Dialog traces

The `a_until_dialog_end` helper presses A repeatedly to clear text the model would otherwise burn
turns on. Because that helper can do real damage if it fires at the wrong moment (starting a
conversation, picking a highlighted menu item, typing a character into a naming box), every internal
press writes its own `dialog.trace` entry: the UI/textbox/menu flags, the text on screen, and whether
the screen settled after release.

`dialog.stop_reason` is one of `closed`, `choice`, `menu`, or `capped`. Collected helper text is kept
in full. When a history quote is shortened for the prompt, the line says how many lines it dropped, so
a short quote is never mistaken for the whole conversation.
