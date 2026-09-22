#!/usr/bin/env python3
"""Qwen (local, on the Unraid Ollama box) plays Pokemon Red through pokemon-agent's REST API.

Loop: GET /frame -> model returns thought + 1-6 button actions
      -> POST /event (narration to the dashboard) -> POST /action/traced -> repeat.
The wrapper keeps the game running in real time between turns (NPCs move, animations finish), so the screenshot is a moment in time and the game is not paused while Qwen thinks.

  qwen_red.py [--turns N] [--model qwen3.8:27b] [--think low|medium|high] [--server http://localhost:8765]
"""
import argparse
import base64
import hashlib
import io
import json
import os
import subprocess
import time

import requests
from PIL import Image

from milestones import MilestoneTracker, MILESTONES

HERE = os.path.dirname(os.path.abspath(__file__))
OLLAMA = os.environ.get("OLLAMA_HOST", "http://localhost:11434")
RUNS_DIR = os.path.join(HERE, "runs")

SYSTEM = """__IDENTITY__ You get the game state read from RAM, an ASCII walkability map, and a screenshot. The game keeps running in real time between turns (NPCs move, animations finish), so the screenshot is a moment in time; each turn only 1-6 button presses happen.

How the game works: overworld movement is one tile per walk_X. Talk to people/signs with press_a while facing them. DOORS, STAIRS, and building entrances are WARP tiles: you trigger them by WALKING ONTO them, never with A (the one exception is an EXIT MAT inside a building, explained under Map reading). Enterable warp tiles are marked on the ASCII map (read from the game's own warp table and collision data): `D` = a door between inside and outside (a building's street entrance from the outside, or its exit mat from the inside), `S` = a warp to some OTHER map (stairs to another floor, a cave mouth, the far side of a gate house). A `.` is never a door. In menus and dialog, press_a advances/confirms, press_b cancels. a_until_dialog_end presses A through dialogue until the text box closes or a choice/menu appears (up to 100 presses); it does nothing when no text box is open. ★SCREEN TEXT below is exactly what is written on screen right now, read from the game's memory; dialogue a_until_dialog_end skipped past is quoted back to you in RECENT TURNS, with omitted lines counted if a quote is shortened. You cannot walk while a text box is open. The title/intro screens need press_start then press_a. Name entry (yours, then your rival's): move onto a preset name and press_a, or pick NEW NAME: on the letter grid walk_X moves the cursor, press_a types the highlighted letter, press_b deletes; to finish, move the cursor to the ED (end) tile at the bottom-right and press_a, or press_start to submit.

Map reading: the ASCII map is 10 columns (A-J) x 9 rows (1-9); you are @ at E5. The grid is a WINDOW that moves with you: E5 is always your current STATE position (x,y), so grid letters/rows are NOT world coordinates (column A = x-4, J = x+5; row 1 = y-4, row 9 = y+4) and E5 never disagrees with STATE. `.` walkable, `#` blocked, `D` door between inside and outside / `S` warp to another map. Outdoor doors and stairs trigger the moment you step onto them; an EXIT MAT inside a building (the `D` tiles on its edge wall) does not: standing on it, you walk once more INTO the wall behind it (down for a bottom-wall mat, up for a top-wall mat) to go through. `v` is a ledge: walk_down from the tile above it hops you over to the tile below; you can never go back up through it. ★MOVEMENT RULE: you can only step a direction if the tile IMMEDIATELY next to `@` in that direction is `.`, `D`, `S`, or (going down only) `v`. The ONE exception is the exit-mat step above: from a `D` mat you walk into the `#` wall behind it. up = row-1, down = row+1, left = col-1, right = col+1.

Overall goal: beat the game.

Available actions (strings, exactly): press_a, press_b, press_start, press_select, walk_up, walk_down, walk_left, walk_right, hold_a_30, wait_60, a_until_dialog_end.

Reply with JSON only:
{"thought": "<2-3 sentences: what you see, what you intend, why>",
 "actions": ["walk_up", "walk_up", "press_a"],
 "key_moment": "<optional: one line if something notable just happened (new town, badge, catch, starter)>",
 "notes": "<optional: rewrite your persistent notes (where you are, plan, lessons). Under 600 chars>"}
"""

ALLOWED = {"press_a", "press_b", "press_start", "press_select", "walk_up", "walk_down", "walk_left",
           "walk_right", "hold_a_30", "wait_60", "a_until_dialog_end"}
SCHEMA = {
    "type": "object",
    "properties": {
        "thought": {"type": "string"},
        # First line of defence against a name outside ALLOWED, and only that: MEASURED
        # 2026-09-22, Ollama accepts this schema and then ignores the enum -- qwen3:8b asked for
        # press_down returned press_down. So the enum is worth sending, because a backend that
        # does enforce it never emits a bad name, but the runner's own rejection is what actually
        # holds the line. Do not remove that check on the strength of this one.
        # Sorted so the schema is byte-stable across runs -- a set's order is not, and this goes
        # into the request every turn.
        "actions": {"type": "array", "items": {"type": "string", "enum": sorted(ALLOWED)}},
        "key_moment": {"type": "string"},
        "notes": {"type": "string"},
    },
    "required": ["thought", "actions"],
}

# Provenance (BENCHMARK-SPEC.md §2b — same prompt, same rules, public receipts).
# v22 = STATE no longer reports the starter-preview dex count as owned, and an action outside
#       ALLOWED is rejected instead of silently dropped from the batch
# v21 = STATE says "none loaded yet" on the title/intro instead of Red's House 2F (3,6)
# v20 = door rule no longer contradicts the exit-mat rule
# v19 = map shows raw walkability, no reachability flood-fill
# v18 = truthful warp/UI/party/feedback
PROMPT_VERSION = "v22"
HARNESS_VERSION = 2
NUM_CTX = 65536
TEMPERATURE = 0.6
NUM_PREDICT = None          # None = uncapped, matching providers.py. An 8192 ceiling made qwen3.8:27b
                            # burn the whole budget on thinking and reply empty 11 times in 242 turns.
                            # The 600s per-turn timeout is the backstop for a runaway.
PROMPT_SHA = hashlib.sha256(SYSTEM.encode()).hexdigest()[:16]  # hashes the __IDENTITY__ template: name-independent "prompt design" fingerprint, stable across models

# The opening identity sentence is the ONLY model-specific part of the prompt. Same framing for
# every model so runs stay comparable; only the name changes ("Name only" per Cody, 2026-09-09).
IDENTITY_SENTENCES = {
    "qwen": "You are Qwen, a local AI playing Pokémon Red live on stream.",
}
ANTHROPIC_DISPLAY = {  # model-id prefix -> on-prompt name
    "claude-haiku": "Claude Haiku",
    "claude-sonnet": "Claude Sonnet",
    "claude-opus": "Claude Opus",
}
ANTHROPIC_URL = "https://api.anthropic.com/v1/messages"
ANTHROPIC_VERSION = "2023-06-01"
THINK_BUDGET = {"low": 2048, "medium": 4096, "high": 8192}  # extended-thinking token budget per --think level

# Gemini via Vertex AI Express (API key bound to a service account; bills the project's $300 credit).
GEMINI_URL = "https://aiplatform.googleapis.com/v1/publishers/google/models/{model}:generateContent"
AISTUDIO_URL = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"  # AI Studio (GDP free credits); same body, different base
GEMINI_DISPLAY = {"gemini-3.8": "Gemini 3.8 Flash", "gemini-3": "Gemini 3", "gemini-2.5": "Gemini 2.5"}


def infer_provider(model: str) -> str:
    if model.startswith("claude-"):
        return "anthropic"
    if model.startswith("gemini-"):
        return "gemini"
    return "ollama"


def resolve_identity(model: str, provider: str) -> str:
    if provider == "anthropic":
        name = next((v for k, v in ANTHROPIC_DISPLAY.items() if model.startswith(k)), None)
        if not name:  # unknown claude id: title-case the middle token, e.g. claude-foo-5 -> "Claude Foo"
            parts = model.split("-")
            name = "Claude " + (parts[1].capitalize() if len(parts) > 1 else model)
        return f"You are {name}, an AI playing Pokémon Red live on stream."
    if provider == "gemini":
        name = next((v for k, v in GEMINI_DISPLAY.items() if model.startswith(k)), None)
        if not name:  # unknown gemini id: e.g. gemini-3.8-flash -> "Gemini 3.8 Flash"
            toks = model.split("-")[1:]
            name = "Gemini " + " ".join(t.capitalize() for t in toks) if toks else "Gemini"
        return f"You are {name}, an AI playing Pokémon Red live on stream."
    return IDENTITY_SENTENCES.get("qwen")


def render_system(identity: str) -> str:
    return SYSTEM.replace("__IDENTITY__", identity)


def compact(state):
    p = state.get("player", {}) or {}
    party = [(f"{m.get('species') or m.get('nickname') or 'Pokémon'} (initializing)"
              if not m.get("level") or m.get("max_hp") == 0 else
              f"{m.get('nickname')}({m.get('species')}) L{m.get('level')} HP {m.get('hp')}/{m.get('max_hp')}"
             + (f" {m.get('status')}" if m.get('status') else "") + " moves " + ",".join(
                 mv.get("name") if isinstance(mv, dict) else str(mv) for mv in m.get("moves", [])))
             for m in state.get("party", []) or []]
    b = state.get("battle") or {}
    sm = state.get("map") or {}
    # Title screen / Oak's intro: RAM already holds Red's House 2F (3,6) but no map is loaded yet.
    # A run once cited that "location" as proof its save was corrupt, so say plainly there is none.
    where = (f"map: {sm.get('map_name')}  pos {p.get('position')}  facing {p.get('facing')}" if sm.get("loaded", True)
             else "map: none loaded yet (title screen or intro)  pos none")
    lines = [
        f"{where}  money {p.get('money')}  badges {p.get('badges')}",
        "party: " + ("; ".join(party) if party else "none"),
        "bag: " + (", ".join(f"{i.get('item')}x{i.get('quantity')}" for i in state.get("bag", []) or []) or "empty"),
        f"in_battle: {b.get('in_battle')}",
    ]
    if b.get("in_battle"):
        lines.append("battle: " + json.dumps({k: v for k, v in b.items() if k != "in_battle"})[:400])
    fl = state.get("flags") or {}
    in_bag = any("PARCEL" in str(i.get("item", "")).upper() for i in state.get("bag", []) or [])
    parcel = "in your bag" if in_bag else ("already delivered to Oak" if fl.get("has_oaks_parcel") else "not yet picked up")
    # The starter-pick screen sets the owned bits for the three starters plus Ivysaur to draw its
    # preview, then clears them (pokered engine/events/starter_dex.asm). Reporting "owned 4" with an
    # empty party told the model it had caught Pokemon it had never seen. Qualified rather than
    # silently zeroed so the log record, which is this string, still shows what the RAM said.
    owned = fl.get("pokedex_owned")
    owned_text = (f"0 (starter preview is showing {owned})"
                  if not party and isinstance(owned, int) and owned > 0 else owned)
    lines.append(f"flags: pokedex {fl.get('has_pokedex')}, parcel {parcel}, seen {fl.get('pokedex_seen')} owned {owned_text}")
    return "\n".join(lines)


def shrink_png(png_bytes: bytes) -> str:
    im = Image.open(io.BytesIO(png_bytes)).convert("RGB").resize((480, 432), Image.NEAREST)
    buf = io.BytesIO(); im.save(buf, "PNG")
    return base64.b64encode(buf.getvalue()).decode()


def screenshot_b64(server: str) -> str:
    """Fetch the live frame and return the shrunk PNG as base64 (the wire image providers send)."""
    frame = requests.get(f"{server}/frame", timeout=20).json()
    return shrink_png(base64.b64decode(frame["screenshot_b64"]))


def ask(model, think, system, user, image_b64):
    r = requests.post(f"{OLLAMA}/api/chat", json={
        "model": model, "stream": False, "format": SCHEMA, "think": think, "keep_alive": "30m",
        "messages": [{"role": "system", "content": system},
                     {"role": "user", "content": user, "images": [image_b64]}],
        "options": {"num_ctx": NUM_CTX, "temperature": TEMPERATURE,
                    "num_predict": -1 if NUM_PREDICT is None else NUM_PREDICT},
    }, timeout=600)
    r.raise_for_status()
    body = r.json()
    msg = body["message"]
    tokens = {"prompt": body.get("prompt_eval_count", 0), "completion": body.get("eval_count", 0)}
    return msg["content"], msg.get("thinking", ""), tokens


def _extract_json(text: str) -> str:
    """Pull the JSON object out of a model text reply: strip a ```json fence, else slice first { .. last }.
    The caller's json.loads + parse-error path still guards anything this misses."""
    t = text.strip()
    if t.startswith("```"):
        t = t.split("\n", 1)[-1] if "\n" in t else t
        t = t.rsplit("```", 1)[0].strip()
        if t.lower().startswith("json"):
            t = t[4:].strip()
    i, j = t.find("{"), t.rfind("}")
    return t[i:j + 1] if i != -1 and j > i else t


def ask_anthropic(model, think, system, user, image_b64):
    """Anthropic Messages API adapter. Returns the same (content_json_str, thinking, tokens) tuple as ask().

    Extended thinking is ON (reasoning parity with Qwen's `think=high`, per BENCHMARK-SPEC line-318 invariant).
    Thinking forces temperature=1 on the API, so we omit temperature. JSON comes from the text block and is
    parsed by the caller's existing json.loads + parse-error fallback; the reasoning fills the `thinking` field.
    """
    key = os.environ.get("ANTHROPIC_API_KEY")
    if not key:
        raise RuntimeError("ANTHROPIC_API_KEY not set in the container env")
    headers = {"x-api-key": key, "anthropic-version": ANTHROPIC_VERSION, "content-type": "application/json"}
    ws = os.environ.get("ANTHROPIC_WORKSPACE_ID")  # org-scoped keys need this to bill the right workspace's credits
    if ws:
        headers["anthropic-workspace-id"] = ws
    budget = THINK_BUDGET.get(think, THINK_BUDGET["high"])
    r = requests.post(ANTHROPIC_URL, headers=headers, json={
        "model": model, "max_tokens": budget + 1024, "system": system,  # +1024 headroom for the JSON answer after thinking
        "thinking": {"type": "enabled", "budget_tokens": budget},
        "messages": [{"role": "user", "content": [
            {"type": "image", "source": {"type": "base64", "media_type": "image/png", "data": image_b64}},
            {"type": "text", "text": user},
        ]}],
    }, timeout=600)
    r.raise_for_status()
    body = r.json()
    text = "".join(b.get("text", "") for b in body.get("content", []) if b.get("type") == "text")
    thinking = "".join(b.get("thinking", "") for b in body.get("content", []) if b.get("type") == "thinking")
    usage = body.get("usage", {})
    tokens = {"prompt": usage.get("input_tokens", 0), "completion": usage.get("output_tokens", 0)}
    return _extract_json(text), thinking, tokens


def ask_gemini(model, think, system, user, image_b64):
    """Gemini via Vertex AI Express. Returns the same (content_json_str, thinking, tokens) tuple as ask().

    Gemini 3.x reasons by default (its recommended setting = the benchmark's 'max reasoning' invariant), so
    `think` is unused; responseMimeType application/json makes it emit the schema JSON without a tool call,
    parsed by the caller's json.loads + parse-error fallback.
    """
    studio = os.environ.get("GEMINI_API_KEY")  # AI Studio key (GDP credits ~ free); preferred when present
    if studio:
        url, key = AISTUDIO_URL.format(model=model), studio
    else:
        key = os.environ.get("GOOGLE_API_KEY")
        if not key:
            raise RuntimeError("no Gemini key: set GEMINI_API_KEY (AI Studio) or GOOGLE_API_KEY (Vertex Express)")
        url = GEMINI_URL.format(model=model)
    r = requests.post(url, headers={
        "x-goog-api-key": key, "Content-Type": "application/json",
    }, json={
        "systemInstruction": {"parts": [{"text": system}]},
        "contents": [{"role": "user", "parts": [
            {"inline_data": {"mime_type": "image/png", "data": image_b64}},
            {"text": user},
        ]}],
        "generationConfig": {"responseMimeType": "application/json",
                             **({} if NUM_PREDICT is None else {"maxOutputTokens": NUM_PREDICT})},
    }, timeout=600)
    r.raise_for_status()
    body = r.json()
    parts = (((body.get("candidates") or [{}])[0]).get("content") or {}).get("parts") or []
    text = "".join(p.get("text", "") for p in parts if not p.get("thought"))
    thinking = "".join(p.get("text", "") for p in parts if p.get("thought"))  # 3.x thoughts are usually opaque
    um = body.get("usageMetadata") or {}
    tokens = {"prompt": um.get("promptTokenCount", 0),
              "completion": um.get("candidatesTokenCount", 0) + um.get("thoughtsTokenCount", 0)}
    return _extract_json(text), thinking, tokens


def ask_model(provider, model, think, system, user, image_b64):
    if provider == "anthropic":
        return ask_anthropic(model, think, system, user, image_b64)
    if provider == "gemini":
        return ask_gemini(model, think, system, user, image_b64)
    return ask(model, think, system, user, image_b64)


def event(server, typ, **kw):
    try:
        requests.post(f"{server}/event", json={"type": typ, **kw}, timeout=10)
    except Exception:
        pass


def write_summary(artifact_dir, run_id, model, run_name, think, tracker, turns_used, budget,
                  tokens, wall_s, notes, in_game_name="", rival_name="", frames_saved=True, acts=None,
                  provider="ollama-local", family="qwen", execution_route="ollama-local",
                  model_params="27B", quant="Q4_K_M", cost_usd=0.0, num_ctx=NUM_CTX, temperature=TEMPERATURE):
    """Emit the per-run scoring + provenance JSON the leaderboard reads (BENCHMARK-SPEC.md §2/§2b)."""
    # harness provenance
    try:
        harness_git_sha = subprocess.check_output(["git", "-C", HERE, "rev-parse", "--short", "HEAD"], text=True, timeout=5).strip()
    except Exception:  # container has no .git: deploy drops the sha in env or a GIT_SHA file next to us
        harness_git_sha = os.environ.get("POKEBENCH_GIT_SHA")
        if not harness_git_sha and os.path.exists(os.path.join(HERE, "GIT_SHA")):
            harness_git_sha = open(os.path.join(HERE, "GIT_SHA")).read().strip() or None
    try:
        h_bytes = open(os.path.join(HERE, "qwen_red.py"), "rb").read() + open(os.path.join(HERE, "serve_live.py"), "rb").read()
        harness_files_sha = hashlib.sha256(h_bytes).hexdigest()[:16]
    except Exception:
        harness_files_sha = None
    summary = {
        "run_id": run_id, "model": model, "provider": provider, "family": family,
        "run_name": run_name,
        # the name the model gave itself / its rival in-game (personality for the card)
        "in_game_name": in_game_name, "rival_name": rival_name,
        # --- provenance / receipts ---
        "prompt_version": PROMPT_VERSION, "prompt_sha": PROMPT_SHA,
        "harness_version": HARNESS_VERSION, "execution_route": execution_route,
        "harness_git_sha": harness_git_sha, "harness_files_sha": harness_files_sha, "frames_saved": frames_saved,
        "think_level": think, "num_ctx": num_ctx, "temperature": temperature, "num_predict": NUM_PREDICT,
        "allowed_actions": sorted(ALLOWED),
        "run_date": time.strftime("%Y-%m-%d"), "model_release_date": None,  # filled via models.yaml (phase 2)
        "model_params": model_params, "quant": quant,
        "artifacts": {"log": "log.jsonl", "save_state": run_id},
        "notes": notes,
        # --- scoring ---
        "budget_turns": budget, "turns_used": turns_used, "wall_time_s": round(wall_s, 1),
        "tokens_in": tokens["prompt"], "tokens_out": tokens["completion"],
        # how boldly the model uses its 6-action cap (REPORT, not score): actions it chose per acted turn,
        # plus how many A presses a_until_dialog_end spent on its behalf
        "acted_turns": (acts or {}).get("turns", 0), "actions_total": (acts or {}).get("actions", 0),
        "avg_actions_per_turn": round((acts or {}).get("actions", 0) / (acts or {}).get("turns", 1), 2) if (acts or {}).get("turns") else None,
        "a_until_presses_total": (acts or {}).get("a_presses", 0),
        "model_errors": (acts or {}).get("model_errors", 0),  # Ollama/API failures that re-ran a turn (not counted against the budget)
        "cost_usd": cost_usd,  # ollama-local = 0.0; anthropic left None unless a price rate is provided
        "youtube_url": None, "timestamp": time.strftime("%Y%m%d_%H%M%S"),
        **tracker.summary(),
    }
    path = os.path.join(artifact_dir, "summary.json")
    with open(path, "w") as f:
        json.dump(summary, f, indent=2)
    print(f"\n=== RUN SUMMARY -> {path} ===")
    print(f"furthest: {summary['furthest_label']} (idx {summary['furthest_index']}) | "
          f"turns {turns_used}/{budget} | tok in/out {tokens['prompt']}/{tokens['completion']} | {wall_s:.0f}s")
    return path


def build_map(state, warps=()):
    """Render the walkability grid straight from the collision RAM: `.` walkable, `#` blocked. No
    reachability flood-fill (2026-09-10 audit: it painted 292 walkable tiles as `#`, mostly Pewter City,
    because "no route inside this window" is not "blocked terrain"). Warp tiles (doors, stairs) from the
    game's warp table render as `D`/`S` (test run 4: a door shown as `.` cost ~95 turns of re-entering home)."""
    c = state.get("collision") or {}
    grid = c.get("walkable")
    cell = c.get("player_cell") or "E5"
    if not grid:
        return None
    rows, cols = len(grid), len(grid[0])
    pc = ord(cell[0].upper()) - ord("A"); pr = int(cell[1:]) - 1
    ids = c.get("tile_ids") or []
    ledge_down = set()
    if c.get("tileset") == 0 and ids:  # overworld tileset: 0x36/0x37 are the one-way ledge tiles you hop DOWN over
        for r in range(rows):
            for cc in range(cols):
                if r < len(ids) and cc < len(ids[r]) and ids[r][cc] in (0x36, 0x37):
                    ledge_down.add((r, cc))
    ppos = (state.get("player") or {}).get("position") or {}
    doors, stairs = set(), set()
    outdoors = c.get("tileset") == 0
    if ppos.get("x") is not None:
        for w in warps or ():
            wx, wy = w[0], w[1]
            dest = w[2] if len(w) > 2 else 0xFF
            cell_rc = (wy - ppos["y"] + pr, wx - ppos["x"] + pc)  # world -> window: @ sits at (pr, pc)
            # outdoors every warp is a building entrance (D); indoors only LAST_MAP (0xFF) leads back outside,
            # the rest are stairs/passages to another indoor map (S). Test run 6: stairs shown as D = 15-turn 1F<->2F loop.
            (doors if outdoors or dest == 0xFF else stairs).add(cell_rc)
    out = ["   " + " ".join(chr(ord("A")+x) for x in range(cols))]
    for r in range(rows):
        line = []
        for cc in range(cols):
            if (r, cc) == (pr, pc): line.append("@")
            elif (r, cc) in doors and grid[r][cc]: line.append("D")
            elif (r, cc) in stairs and grid[r][cc]: line.append("S")
            elif (r, cc) in ledge_down: line.append("v")
            elif grid[r][cc]: line.append(".")
            else: line.append("#")
        out.append(f"{r+1:2d} " + " ".join(line))
    out.append("@ you  . walkable  # blocked  D door (inside<->outside)  S warp to another map (stairs/cave/far side of a gate)  v ledge (hop DOWN over it; one-way)")
    out.append("up=row-1 down=row+1 left=col-1 right=col+1")
    return "\n".join(out)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--turns", type=int, default=1000)  # locked benchmark budget
    ap.add_argument("--model", default="qwen3.8:27b")
    ap.add_argument("--think", default="high")  # LOCKED benchmark level: each model at its recommended/max reasoning
    ap.add_argument("--server", default="http://localhost:8765")
    ap.add_argument("--save-every", type=int, default=25)
    ap.add_argument("--run-name", default="")
    ap.add_argument("--no-frames", action="store_true", help="don't save frame PNGs")
    ap.add_argument("--provider", default="auto", choices=["auto", "ollama", "anthropic", "gemini"],
                    help="auto = infer from --model (claude-* -> anthropic, gemini-* -> gemini, else ollama)")
    ap.add_argument("--identity", default="",
                    help="override the opening identity sentence; default derived from the model")
    args = ap.parse_args()
    S = args.server

    provider = args.provider if args.provider != "auto" else infer_provider(args.model)
    identity = args.identity or resolve_identity(args.model, provider)
    system_prompt = render_system(identity)
    if provider == "anthropic":
        # Extended thinking ON forces temperature=1 and has no num_ctx analog. Record what the call actually did.
        prov_fields = dict(provider="anthropic", family="claude", execution_route="anthropic-api",
                           model_params=None, quant=None, cost_usd=None,  # cost left null: no fabricated rate
                           num_ctx=None, temperature=1.0)
        rec_think = args.think  # real: thinking runs at THINK_BUDGET[args.think]
    elif provider == "gemini":
        # Gemini 3.x reasons by default; no num_ctx analog, temperature left at the API default.
        _studio = bool(os.environ.get("GEMINI_API_KEY"))  # AI Studio (GDP credits) vs Vertex Express
        prov_fields = dict(provider=("google-aistudio" if _studio else "vertex-express"), family="gemini",
                           execution_route=("aistudio-api" if _studio else "vertex-express-api"),
                           model_params=None, quant=None, cost_usd=None, num_ctx=None, temperature=None)
        rec_think = "default"  # Gemini 3.x thinking is on by default; we don't override the level
    else:
        prov_fields = dict(provider="ollama-local", family="qwen", execution_route="ollama-local",
                           model_params="27B", quant="Q4_K_M", cost_usd=0.0,
                           num_ctx=NUM_CTX, temperature=TEMPERATURE)
        rec_think = args.think

    tracker = MilestoneTracker()
    run_start = time.time()
    tok = {"prompt": 0, "completion": 0}
    acts = {"turns": 0, "actions": 0, "a_presses": 0}
    turn = 0
    run_id = f"{args.model.replace(':', '-').replace('.', '-')}-{time.strftime('%Y%m%d_%H%M%S')}"
    artifact_dir = os.path.join(RUNS_DIR, run_id)
    os.makedirs(artifact_dir, exist_ok=True)
    if not args.no_frames:
        os.makedirs(os.path.join(artifact_dir, "frames"), exist_ok=True)
    log_path = os.path.join(artifact_dir, "log.jsonl")
    notes_path = os.path.join(artifact_dir, "notes.md")
    print(f"run artifacts -> {artifact_dir}  (prompt {PROMPT_VERSION}/{PROMPT_SHA}, ctx {NUM_CTX})", flush=True)

    # Register a fresh tracked game session: boots the emulator clean AND makes the
    # dashboard's turn/action counters increment (/action only counts with an active
    # session) and gives the stream timer a server-side created_at anchor.
    run_label = args.run_name or run_id
    try:
        requests.post(f"{S}/games/new", json={"name": run_label}, timeout=45)
        print(f"registered game session '{run_label}' (fresh boot)", flush=True)
        try:  # tells the /stream page which model is playing (sprite colors, kicker)
            requests.post(f"{S}/run_meta", json={"model": args.model, "think": rec_think,
                                                 "ctx": (NUM_CTX if provider == "ollama" else None),  # NUM_CTX is Ollama-only; API models use their own (much larger) window
                                                 "route": ("local" if provider == "ollama" else "api"), "prompt_version": PROMPT_VERSION}, timeout=10)
        except Exception:
            pass
    except Exception as e:
        print(f"WARN: /games/new failed ({e}); counters/timer may not populate", flush=True)
    # /games/new leaves control at its default; ensure the loop is allowed to run.
    try:
        requests.post(f"{S}/control", json={"state": "running"}, timeout=10)
    except Exception:
        pass

    notes = "(no notes yet)"
    history = []
    in_game_name = ""; rival_name = ""  # captured once she names herself / the rival
    # `turn` only advances on a real decision: a pause, an unreachable server, or a model/Ollama outage re-runs
    # the same turn number (test run 7: the 2 AM appdata backup stopped Ollama and 41 turns burned on
    # connection errors; the paused path also ate a turn every 3 s).
    turn = 0
    model_errors = 0
    while turn < args.turns:
        turn += 1
        try:
            ctl = requests.get(f"{S}/control", timeout=10).json().get("state", "running")
        except Exception:
            ctl = "running"
        if ctl == "paused":
            turn -= 1; time.sleep(3); continue
        if ctl == "stopped":
            print("control = stopped, exiting"); break

        try:
            frame = requests.get(f"{S}/frame", timeout=20).json()
            state = frame["state"]
            screen_text = frame.get("screen_text") or "(nothing written on screen)"
            # A text box or menu overwrites the bottom rows of the tilemap, and the collision map is
            # read from that tilemap, so those rows render as false `#` walls (Codex run-9 review,
            # T168/T229: she walked onto cells shown blocked once the box cleared). She cannot walk
            # while a box is up anyway, so hide the map until it is cleared instead of showing a lie.
            if frame.get("dialog_open") or frame.get("screen_text"):
                amap = "(map hidden while text is on screen)"
            elif frame.get("settle") == "capped":
                amap = "(map hidden while frame is unsettled)"
            elif frame.get("menu_open") or frame.get("in_battle"):
                amap = "(no map: in battle or menu)"
            else:
                amap = build_map(state, frame.get("warps") or ()) or frame.get("ascii") or "(no map: in battle or menu)"
            png_bytes = base64.b64decode(frame["screenshot_b64"])
            screenshot_sha256 = hashlib.sha256(png_bytes).hexdigest()
            if args.no_frames:
                frame_file = None
            else:
                fname = f"turn_{turn:04d}.png"
                fpath = os.path.join(artifact_dir, "frames", fname)
                try:
                    open(fpath, "wb").write(png_bytes)
                    frame_file = os.path.join("frames", fname)
                except Exception:
                    frame_file = None
            img = shrink_png(png_bytes)
        except Exception as e:
            print(f"[turn {turn}] server not reachable ({e}); retrying"); turn -= 1; time.sleep(5); continue
        _pl = state.get("player") or {}
        if _pl.get("name"): in_game_name = _pl["name"]
        if _pl.get("rival_name"): rival_name = _pl["rival_name"]
        def check_milestones(st, t):
            was = set(tracker.first_turn)
            tracker.update(st, t)
            for key, label, _ in MILESTONES:
                if key in tracker.first_turn and key not in was:
                    print(f"🏁 MILESTONE: {label} (turn {t})", flush=True)
                    event(S, "key_moment", description=f"Milestone: {label}", category="milestone")
                    try:
                        requests.post(f"{S}/milestones", json={"key": key, "label": label, "turn": t}, timeout=10)
                    except Exception:
                        pass
        check_milestones(state, turn)
        if "beat_brock" in tracker.first_turn:
            print(f"🏆 Brock defeated at turn {turn} — ceiling reached, ending run.", flush=True)
            break
        user = (f"YOUR PRIOR NOTES (you wrote these on earlier turns; they are plans and guesses, NOT verified observations — the STATE, map and screenshot below are the truth):\n{notes}\n\nRECENT TURNS:\n" + "\n".join(history[-12:]) +
                f"\n\nSTATE:\n{compact(state)}\n\nSCREEN TEXT (words on screen right now):\n{screen_text}\n\nWALKABILITY MAP (you are @ at E5):\n{amap}\n\nThe screenshot is attached. Take your turn.")
        t0 = time.time()
        retried = False
        try:
            content_str, thinking, tokens = ask_model(provider, args.model, args.think, system_prompt, user, img)
            if not content_str.strip():
                # Ollama structured output sometimes ends the reply inside the thinking and returns empty content
                # (test run 3: T19, T31; local smoke T2). A serving glitch, not a decision: one retry, logged.
                retried = True
                c2, th2, tk2 = ask_model(provider, args.model, args.think, system_prompt, user, img)
                tokens = {"prompt": tokens["prompt"] + tk2["prompt"], "completion": tokens["completion"] + tk2["completion"]}
                content_str, thinking = c2, (thinking + "\n---retry---\n" + th2)
        except Exception as e:
            status = getattr(getattr(e, "response", None), "status_code", None)
            if status in (400, 401, 403):  # bad request / key / scope: config error, won't self-heal, abort loudly
                detail = getattr(getattr(e, "response", None), "text", "")[:300]
                print(f"[turn {turn}] FATAL: model API {status} — config error, not transient. Aborting run.\n{detail}", flush=True)
                raise SystemExit(2)
            model_errors += 1; acts["model_errors"] = model_errors
            with open(log_path, "a") as f:
                f.write(json.dumps({"turn": turn, "prompt_version": PROMPT_VERSION, "model_error": str(e), "turn_not_counted": True,
                                    "model_error_count": model_errors, "screenshot_sha256": screenshot_sha256}) + "\n")
            print(f"[turn {turn}] model error #{model_errors}: {e}; retrying the same turn in 15 s")
            turn -= 1; time.sleep(15); continue
        dt = time.time() - t0
        # parse JSON in caller
        try:
            plan = json.loads(content_str)
            if not isinstance(plan, dict):
                raise ValueError(f"reply is {type(plan).__name__}, not an object")
        except Exception as e:
            tok["prompt"] += tokens["prompt"]; tok["completion"] += tokens["completion"]
            with open(log_path, "a") as f:
                f.write(json.dumps({"turn": turn, "prompt_version": PROMPT_VERSION, "parse_error": str(e), "raw_response": content_str, "thinking": thinking, "tokens": tokens, "retried": retried, "user_message": user, "screenshot_sha256": screenshot_sha256, "model_s": dt}) + "\n")
            print(f"[turn {turn}] parse error: {e}")
            mp = (state.get("map") or {}).get("map_name") or "Unknown"
            pp = (state.get("player") or {}).get("position") or {}
            history.append(f"turn {turn}: {mp} ({pp.get('x')},{pp.get('y')}) -> (model reply was not valid JSON, no actions)")
            continue
        tok["prompt"] += tokens["prompt"]; tok["completion"] += tokens["completion"]
        thought = (plan.get("thought") or "").strip()
        plan_actions_raw = plan.get("actions") or []
        actions = [a for a in plan_actions_raw if a in ALLOWED][:6] if isinstance(plan_actions_raw, list) else []
        fallback_reason = None
        if not actions:
            actions = ["wait_60"]
            fallback_reason = "empty_or_invalid_plan"
            print(f"⚠ fallback wait_60 (plan had no valid actions)", flush=True)
        print(f"\n=== turn {turn} | {compact(state).splitlines()[0]} | model {dt:.0f}s ===", flush=True)
        print(f"💭 {thought}", flush=True)
        print(f"  ▶ {' '.join(actions)}", flush=True)
        event(S, "reasoning", text=thought)
        event(S, "decision", text=" ".join(actions))
        if plan.get("key_moment"):
            event(S, "key_moment", description=plan["key_moment"][:200], category="milestone")
        # traced action: history line = start pose -> actions -> end pose (+ what the batch actually did)
        def pose_of(st):
            sm = st.get("map") or {}; sp = (st.get("player") or {}).get("position") or {}
            return {"map_id": sm.get("map_id"), "map_name": sm.get("map_name"), "pos": [sp.get("x"), sp.get("y")]}
        def fmt(p): return f"{p.get('map_name') or 'Unknown'} ({(p.get('pos') or [None, None])[0]},{(p.get('pos') or [None, None])[1]})"
        steps = []; start = end = pose_of(state); tail_parts = []; rj = {}
        try:
            r = requests.post(f"{S}/action/traced", json={"actions": actions}, timeout=120)
            r.raise_for_status()
            rj = r.json()
            steps = rj.get("steps", [])
            if steps:
                start = steps[0].get("before") or start
                end = next((st["after"] for st in reversed(steps) if st.get("after")), start)  # error steps have no pose
            seen = pose_of(state)
            if start.get("map_id") != seen.get("map_id") or start.get("pos") != seen.get("pos"):
                tail_parts.append(f" (the game moved you before your input: {fmt(seen)} -> {fmt(start)})")  # scripted scene ran while you thought
            ui_turn = all(st.get("before", {}).get("ui") for st in steps if st.get("before"))
            if start.get("map_id") == end.get("map_id") and start.get("pos") == end.get("pos"):
                moved = any(p.get("map_id") != start.get("map_id") or p.get("pos") != start.get("pos")
                            for st in steps for p in (st.get("before"), st.get("after")) if p)
                tail_parts.append(" (back at the starting position)" if moved else
                                  " (menu/dialog input, position unchanged)" if ui_turn and steps else " (no movement)")
            elif start.get("map_id") != end.get("map_id"):
                tail_parts.append(f" MAP CHANGED {start.get('map_name')} -> {end.get('map_name')}")
            blocked = {}
            for st in steps:
                b, af = st.get("before"), st.get("after")
                if b and (b.get("ui") or (af and af.get("ui"))):
                    continue  # cursor move inside a menu/dialog/battle, or the step itself triggered a scene/battle
                if st.get("action", "").startswith("walk_") and b and af and b.get("map_id") == af.get("map_id") and b.get("pos") == af.get("pos"):
                    blocked[st["action"]] = blocked.get(st["action"], 0) + 1
            if blocked:
                tail_parts.append(" blocked walks: " + ", ".join(f"{k} x{v}" for k, v in blocked.items()))
            pages = []  # every line of dialogue the batch produced, in the order it appeared on screen
            for st in steps:
                if isinstance(st.get("dialog"), dict):
                    tail_parts.append(f" dialog: {st['dialog'].get('stop_reason')} after {st['dialog'].get('presses')} A")
                    for line in st["dialog"].get("text") or []:
                        if line and (not pages or line != pages[-1]):
                            pages.append(line)
                elif st.get("said") and (not pages or st["said"] != pages[-1]):
                    pages.append(st["said"])
                if "error" in st:
                    tail_parts.append(f" action error: {st['error']}")
            if pages:
                shown, used = 0, 0
                for line in pages:
                    used += len(line) + (3 if shown else 0)
                    if used > 1500:
                        break
                    shown += 1
                tail_parts.append(' said: "' + " | ".join(pages[:shown]) + '"')
                if shown < len(pages):
                    tail_parts.append(f" (… {len(pages) - shown} more lines not shown)")
            if isinstance(rj.get("state_after"), dict):
                check_milestones(rj["state_after"], turn)  # the turn that produced the milestone, not the next one
        except Exception as e:
            tail_parts.append(f" action error: {e}")
        result_tail = "".join(tail_parts)
        history_line = f"turn {turn}: {fmt(start)} -> [{' '.join(actions)}] -> {fmt(end)}{result_tail}"
        if plan.get("notes"):
            notes = plan["notes"][:600]
            try:
                open(notes_path, "w").write(notes)
            except Exception:
                pass
        history.append(history_line)
        acts["turns"] += 1; acts["actions"] += len(actions)
        acts["a_presses"] += sum((st.get("dialog") or {}).get("presses", 0) for st in steps if isinstance(st.get("dialog"), dict))
        with open(log_path, "a") as f:
            f.write(json.dumps({"turn": turn, "prompt_version": PROMPT_VERSION, "user_message": user, "screenshot_sha256": screenshot_sha256, "frame_file": frame_file, "state": state, "screen_text": screen_text, "thinking": thinking, "plan": plan, "plan_actions_raw": plan_actions_raw, "actions": actions, "fallback_reason": fallback_reason, "steps": steps, "result": result_tail, "model_s": dt, "tokens": tokens, "retried": retried, "warps": frame.get("warps"), "state_after": rj.get("state_after")}) + "\n")
        if turn % args.save_every == 0:
            try:
                requests.post(f"{S}/save", json={"name": run_id}, timeout=30)
            except Exception:
                pass

    final_notes = open(notes_path).read() if os.path.exists(notes_path) else ""
    write_summary(artifact_dir, run_id, args.model, args.run_name or "run", rec_think, tracker,
                  turn, args.turns, tok, time.time() - run_start, final_notes,
                  in_game_name=in_game_name, rival_name=rival_name, frames_saved=not args.no_frames, acts=acts,
                  **prov_fields)


if __name__ == "__main__":
    main()
