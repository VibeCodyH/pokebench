You are auditing PokéBench, a harness where a vision LLM plays Pokémon Red on a fixed 1,000-turn budget. READ-ONLY review: do not edit files. Repo root is the cwd.

Run under review: runs/gemini-3-8-flash-20260910_031005-e6ljyr2c/ — Gemini 3.8 Flash on prompt v17, harness git sha babc1a3. It beat Brock at turn 501. log.jsonl has 500 records (turn 231 is missing: a Google 503 consumed the turn with no record; that bug is already fixed in d797b71, do not re-report it). console.log is the same run's console output. summary.json is the scored result.

Files that matter:
- run_benchmark.py — the turn loop actually used for this run (NOT qwen_red's loop). Prompt assembly (NOTES / RECENT TURNS / STATE / SCREEN TEXT / WALKABILITY MAP), action filtering, history line construction ("turn N: pose did [...] -> pose ..."), milestone credit, blackout detection, log.jsonl writing.
- qwen_red.py — SYSTEM prompt (v17), compact(state), build_map() (10x9 ASCII map anchored on the player at E5, flood-fill marks walkable-but-unreachable-in-window tiles as #), shrink_png.
- serve_live.py — FastAPI wrapper around the pokemon-agent emulator server: /frame, /action/traced (per-step before/after poses in `steps`), battle reader (_read_battle_active, wEnemyMonPartyPos==$ff means "not sent out yet"), _a_until_dialog_end (RAM text-box check, up to 100 presses).
- milestones.py — the 10-rung ladder; beat_brock ends the run.
- BENCHMARK-SPEC.md, playbook.md — rules are locked; only harness correctness is in scope. Navigation, loop or spatial aids for the model are BANNED by the owner: an accurate description of the world is fine, doing the model's thinking is not. Do not propose hints, stuck warnings, pathing help or coaching.

Each log.jsonl record now carries exactly what the model saw and what happened: `state` (compact state text before), `screen_text` (words on screen before), `map` (the ASCII map string or the "(map hidden while text is on screen)" placeholder), `feedback` (the history line appended for this turn), `thinking`, `plan` (thought/actions/notes), `result` (execution result), `steps` (per-action before/after from /action/traced), `state_after`, `model_s`, `tokens`.

Questions, in priority order:
1. HARNESS BUGS. Find every turn where what the harness fed the model was wrong or misleading, or where the harness executed something other than what the model asked. Check hard:
   - build_map(): reproduce the grid from `state`/`steps` poses across consecutive turns. Is the player anchored at E5, are warps D/S placed on the right tiles, does the # flood-fill rendering ever paint a tile the model then successfully walks onto (or vice-versa)? Quantify how often the map disagreed with the movement result.
   - "(map hidden while text is on screen)": count turns where the map was hidden while the model was clearly in the overworld and needed it, and turns where screen_text was empty but a text box was actually open (steps show ui=true).
   - Battle reader: any turn where `state` shows an opponent that was not on screen (stale enemy), or "not sent out yet" when a mon was clearly out; any wrong HP/level/status vs the screenshot-derived plan.
   - a_until_dialog_end: turns where it stopped too early (text still open, next action eaten) or too late (pressed A into a menu choice the model did not intend). Use steps before/after ui flags and the model's next-turn reaction.
   - Action execution: blocked walks, drift, actions eaten by an open dialog, the 6-action cap, schema filtering of invalid actions. Any silent divergence between `plan.actions` and `steps`.
   - History/feedback lines: any false or self-reinforcing statement ("MAP CHANGED", "(no movement)", "(menu/dialog input...)") that does not match steps/state_after.
   - Milestone credit turns: verify each of the 10 first-hit turns in summary.json against state_after/steps of that turn; flag any off-by-one or early/late credit.
   - Blackouts: summary.json lacks a `blackouts` field because this process loaded babc1a3; from money halving + map change in state vs state_after, did the model black out at all in this run? (Owner believes no faint occurred.)
   - Token accounting: tokens_in 5,044,673 over 500 turns (~10k/turn). Is that consistent with the prompt size (system + notes + ~12-turn history + state + map + image)? Flag anything that suggests double-counting or an accidentally growing prompt.
2. WASTED TURNS, LABELED. List every episode of 3+ turns with no progress (same position, oscillation, or repeated failed menu input). Label each HARNESS / MODEL / UNSURE with turn numbers and one line of evidence. The Viridian Forest stretch (turns 153-381) is the biggest; characterise it.
3. LOG COMPLETENESS. Is anything still missing from log.jsonl that stopped you settling a HARNESS/MODEL call? Name the minimal field.

Output: a ranked findings list, most impactful first. Each finding: label (HARNESS / MODEL / UNSURE), one-line claim, evidence (turn numbers or file:line), proposed minimal fix (harness only, no coaching). Then a short "clean run?" verdict: would you accept a run on this harness (plus the d797b71 retry fix) as the first recorded result, and if not, exactly what must change first. No code edits. Label speculation as such.
