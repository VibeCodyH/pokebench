You are reviewing PokéBench, a harness where a local 27B vision model (qwen3.8:27b via Ollama) plays Pokémon Red. READ-ONLY review: do not edit files. Repo root is the cwd.

Files that matter:
- qwen_red.py — the agent loop: SYSTEM prompt, compact(state) text, build_map() ASCII walkability map, screenshot_b64 (160x144 -> 480x432 NEAREST), 12-turn history, 600-char notes, "stuck" warning, action allowlist, up to 6 actions per turn.
- serve_live.py — wraps the pokemon_agent FastAPI server (installed package, source at the path python prints for `import pokemon_agent`): action lock, battle reader override, and _a_until_dialog_end (JUST rewritten today to a RAM check: wTileMap 0xC3A0 row 12 col 0 == 0x79 means text box open; in battle a second 0x79 in row 12 = menu up = done).
- milestones.py, playbook.md, BENCHMARK-SPEC.md — scoring and rules (rules are locked; do not propose rule changes, only harness correctness).
- runs/qwen3-8-27b-20260908_032822/log.jsonl — 299 turns of the live run: per turn the compact state text the model saw, its thinking, its JSON plan (thought/actions/notes), and the execution result. runs/qwen3-8-27b-20260908_032822/harness.log — the same run's console log through turn 325.

The question: where does the model get stuck, and for each stuck episode is the cause the HARNESS (what we fed it, how we executed its actions) or the MODEL? The owner's suspicion: the model is smart enough to read a screenshot, so repeated nonsense like "I am inside the Pokémon Center" while standing outdoors in a dead-end corner boxed by trees and fences with one exit suggests we are feeding it something misleading or executing something wrong.

Do this:
1. Walk log.jsonl and find every episode of 3+ turns with no position change or with position oscillating in a small set. List them with turn ranges, map, position, and what the plans were.
2. For each episode, decide HARNESS / MODEL / UNSURE with evidence quoted from the log (turn numbers). Things to check hard:
   - build_map(): is the 10x9 ASCII grid anchored correctly (player at E5), is walkability derived correctly, are warps/doors marked, does the `~` (unreachable) marking ever hide the only exit, does the grid disagree with what the state/screenshot imply? Reproduce its math from the collision data shape the server returns (see the /state response format in the package's server.py and collision.py).
   - Execution semantics: when action 1 of 6 is blocked (walk into a wall, or a dialog still open), the remaining actions still run. Find turns where this produced drift or eaten actions.
   - The state line says nothing about whether a dialog is open (the flag was removed as unreliable). Now that a reliable RAM check exists (_dialog_open), argue whether exposing it in compact(state) would have broken specific loops in the log.
   - The "position unchanged for N turns" warning: does same_pos count correctly, and does the model respond to it?
   - History/notes: does the 12-turn history or the notes field carry stale or self-reinforcing claims (e.g. "inside the Pokémon Center") that keep the model in a false belief? Where did that belief first appear and what in the prompt kept it alive?
   - Screenshot: 480x432 nearest-neighbor of a 4-shade Game Boy frame. Is there anything about how it is produced or described in the SYSTEM prompt that would make a sign post, fence row, or tree line read as an indoor counter/wall?
   - Any JSON schema/parse issue, action-filter issue, or ordering issue (e.g. a_until_dialog_end placed after walks) that the harness silently accepts.
3. Review the new _dialog_open/_a_until_dialog_end for edge cases: Yes/No prompts inside a text box, Mart BUY/SELL, PC menus, name-entry screen, the Start menu, battles (FIGHT box, move box, "used X" text), the 15-press cap on long multi-page text. Which of these would make it stop too early or too late?
4. Note that log.jsonl does not store the ASCII map or screenshot per turn. Say what minimal extra fields would have let you settle the HARNESS/MODEL calls above.

Output: a ranked findings list, most impactful first. Each finding: label (HARNESS/MODEL/UNSURE), one-line claim, evidence (turn numbers or file:line), proposed fix (concrete, minimal). No code edits. Keep speculation labeled as such.
