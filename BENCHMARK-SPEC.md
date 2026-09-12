# PokéBench — Benchmark Build Spec

A funny-but-real LLM benchmark: give every model the same Pokémon Red harness and budget,
score how far it gets. Leaderboard site + YouTube VODs per run. Model-agnostic.
Inspiration: BuseyBench (leaderboard of model runs) — but our scoring is **objective**
(RAM-detected milestones), not a subjective rating.

## 0. Rules (LOCKED 2026-09-07)

- **Gate = TURNS.** Every model gets the **same 1,000-turn budget** (1 turn = up to 6 actions).
  Most actions are one button press; `a_until_dialog_end` is the exception, pressing A until the
  text box closes (up to 100 presses) so that reading a speech costs one action, not thirty.
  Turns measure *decision quality*, independent of GPU speed or verbosity.
- **Score = furthest milestone reached** within budget. Ceiling = **beat Brock (Gym 1)**.
- **Tiebreaker:** same furthest milestone → **fewer turns to reach it** wins.
- **Reasoning level:** every model runs at its **recommended/max reasoning** (Qwen `high`;
  frontier models at their recommended effort, before any overthinking dropoff). Recorded per
  run as `think_level`; runs are only comparable at the same level. (Qwen showed no
  medium-vs-high behavioral delta, so cost isn't a reason to gimp it.)
- **Report (do NOT gate on):** tokens used, USD cost, wall-clock time. These are the
  color/efficiency columns. The hook: "can a free local 27B outrun a $2 API run?"
- Why not the others: **time** just benchmarks the 3090 (a fast dumb model would "win").
  **tokens** are unfair across providers (hidden reasoning tokens, big-context re-reads) —
  good as a cost column, bad as the gate.
- **What the harness may fix:** anything that *misled the model about the game* (a map that
  showed unreachable tiles as walkable, dialog text she could not read, a skip-text action that
  quit early). Never what she should be tracking herself (quest step, where she has been, what
  she already triggered). Game info yes, benchmark-step info no. Per-turn output is
  **uncapped wherever the API allows it** (amended 2026-09-11, corrected 2026-09-12): an 8192
  ceiling made qwen3.8:27b spend the whole budget on thinking and return an empty reply 11 times
  in 242 turns, which is a harness artifact, not a decision. In `run_benchmark.py` Ollama sends
  `num_predict: -1`, and OpenAI and Google omit their cap fields entirely, unless a model's row
  sets `max_output_tokens`, and `qwen_red.py` does the same. One exception, and it is forced:
  the Anthropic Messages API *requires* `max_tokens`, so that adapter sends a high default of
  32,000, which is still an enforced cap. The 600s per-turn timeout is the real backstop.
- **Naming is the model's choice.** The prompt describes both the preset names and the letter grid
  and takes no side. What a model names itself and its rival is part of the run, not a harness rule.

## 0. Eligibility

**Vision-capable models only.** The harness sends a screenshot every turn and the game's text and sprites are
read from it. A text-only model would be playing a different game (ASCII map + SCREEN TEXT alone), so it does not
go on the same board. Candidate list: `docs/model-corpus.md`.

## 1. Milestone ladder (auto-detected from RAM — no human judging)

Ordered checkpoints; each detected from game state we already read. Furthest reached = score.

| # | milestone | detection signal |
|---|-----------|------------------|
| 1 | Left house | map_id leaves Red's House |
| 2 | Got starter | party count ≥ 1 |
| 3 | Reached Route 1 | map_id == Route 1 (Oak intercepts on Pallet's last row, so this lands after the starter) |
| 4 | Reached Viridian City | map_id == Viridian City |
| 5 | Got Oak's Parcel | flags.has_oaks_parcel |
| 6 | Got the Pokédex | flags.has_pokedex |
| 7 | Entered Viridian Forest | map_id == Viridian Forest |
| 8 | Cleared Viridian Forest / reached Pewter | map_id == Pewter City |
| 9 | Entered Brock's gym | map_id == Pewter Gym |
| 10 | **Beat Brock** | badges bit 0 (Boulder) set |

Milestone map_ids come from pokemon-agent's Red memory reader; verify each against a live run
before trusting it (RAM-address confidence: currently *inferred*, must be *measured* per
checkpoint). Store the turn number each milestone first fired.

## 2. Harness generalization (the runner) — SHIPPED

`qwen_red.py` was Ollama-only. The registry runner now covers every provider; this section is
what was built, kept here because the rules depend on it.

- **Provider adapters** — one interface `(system, user, image_b64, schema) -> {thought, actions,...}`:
  - `ollama` (local, done)
  - `anthropic` (Claude — vision + tool/JSON)
  - `openai` (GPT — vision + JSON mode)
  - `google` (Gemini — vision + JSON)
  - Config-driven model list (`models.yaml`: name, provider, family, api params, think level).
- **Fixed budget loop:** stop at 1,000 turns OR Brock, whichever first.
- **Milestone detector** module: each turn, check the ladder, record first-hit turn.
- **Per-run summary JSON** (`runs/<run_id>/summary.json`): model, provider, family,
  harness_version, budget, milestones:[{name, turn}], furthest, turns_used, tokens_in/out,
  cost_usd, wall_time_s, youtube_url, notes.
- **Factual-history fix (shipped):** history stores `pose → actions → pose → result`, NOT the
  model's own narration. Stops the fixation loop where a model re-reads and re-commits to its
  own wrong theory. `run_benchmark.py` windows history back to the first-hit turn of the second
  most recent milestone, then keeps the newest whole entries that still fit the model's
  configured context, 64K by default, after reserving room for the image, the output and
  the rest of the prompt. `qwen_red.py` keeps a
  flat last 12.
- **Determinism caveat (methodology):** in-game RNG (wild encounters, crits) is not fully
  controllable. Fix everything we can — same harness version, same prompt, same budget, same
  start state — and document RNG as a known variance source. Consider N runs/model later.

## 2b. Provenance & receipts (adopted from BuseyBench "same prompt, same rules, public receipts")

A score is worthless without the evidence behind it. Every run preserves, and the site exposes:

- **Prompt version + hash** — the exact system prompt (versioned; runs are only apples-to-apples
  at the same `prompt_version`). Bump the version when the prompt changes; old runs keep theirs.
- **Tool policy** — the allowed action set (press/walk/etc.) + harness_version.
- **Settings** — think level, num_ctx, temperature, num_predict (per-turn output ceiling,
  -1/uncapped unless the model's row sets one), turn budget.
- **Execution route** — how the model was called: `ollama-local`, `anthropic-api`, `openai-api`,
  `google-api`, or `manual`. Labeled because surfaces behave differently (Busey's point).
- **Dates** — run_date AND model_release_date (leaderboard "newest/oldest" sorts by *release*
  date, not run date).
- **Model metadata** — provider, family, params, quant, context length.
- **Artifacts (the receipts)** — the full per-turn log (`log.jsonl`: state, thought, actions,
  result, tokens, timing per turn), the final save-state, and the YouTube VOD. The VOD is the
  ground truth; the milestone score is the sortable structured version of it. **When the score
  and the video disagree, trust the video.**
- **Notes** — free-text per run.

**Retention: append-only, never overwrite.** Each run gets its own dir `runs/<run_id>/`
(`log.jsonl` + `summary.json` + save-state). Runs are immutable once recorded. Versioning the
prompt/harness is what keeps a 2026 run comparable to a later one.

## 3. Benchmark site (static leaderboard)

BuseyBench-style, teal/blue brand to match the channels.

- **Data:** reads `runs.json` (aggregate of the per-run summaries). Static — no backend.
- **Leaderboard (default):** card per run — model, provider/family badge, furthest-milestone
  progress bar, turns / tokens / $ / time, "inspect run" → YouTube VOD, final-screenshot thumb.
- **Filter:** local-vs-API, and by the milestone a run stopped at. Ranking follows the
  tiebreaker above. Sort-by-cost, the compare tray and a timeline page are not built.
- **Host:** Cloudflare Workers, static assets plus one route for the Twitch live check.
  Domain: pokebench.tv.

## 4. Infra / streaming (all on the Unraid box)

Goal: runs + recording live on the box; Cody's PC is only an on-demand viewer.

- **Server + loop → container(s) on the box.** Ollama is local there → lower latency. Deploy
  via Compose Manager / Community Apps (Cody is GUI-first, no CLI). Ollama already lives in the
  `mediastack` compose project.
- **Recorder = headless Chromium (NOT OBS).** Small container loads `localhost:8765/stream`,
  screencasts the full dashboard at 30fps → **NVENC (3090)** → (a) MP4 archive file, (b) RTMP
  push to Twitch. Automated per run, no scenes, no Xvfb babysitting. OBS remains an option for
  hand-produced special streams only.
- **Viewing from PC:** open `http://<server-host>:8765/stream` (or Tailscale) on demand; close
  anytime, run continues. Or watch the Twitch stream.
- **⚠️ VRAM:** 27B@64K = 20.5/24 GB, ~4 GB free. Fine for a 1080p NVENC encode; the collision
  case is a **4K Jellyfin transcode during a recorded run**. Mitigate: 720p encode or drop ctx
  during recording. Not a blocker, a knob.

## 5. Phasing + delegation

Claude plans + reviews; executor team builds (rotate Codex/Grok/Muse). Announce each.

- **Phase 1 — MVP, prove one scored run end-to-end:**
  milestone detector + run-summary JSON + factual-history fix + a minimal static leaderboard
  reading one JSON. Deliverable: one real Qwen run, scored, with a YouTube link on a live card.
- **Phase 2 — fill the board:** provider adapters (Claude/GPT/Gemini) + `models.yaml`. Run a
  few models, populate the leaderboard, add sort/filter/compare.
- **Phase 3 — productionize on Unraid:** dockerize server+loop, headless-Chromium recorder →
  NVENC → Twitch + MP4, GUI-first deploy steps for Cody.

Tracked separately from the live-stream tuning work.
