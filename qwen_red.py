#!/usr/bin/env python3
"""Qwen (local, on the Unraid Ollama box) plays Pokemon Red through pokemon-agent's REST API.

Loop: GET /state + /map/ascii + /screenshot -> model returns thought + 1-6 button actions
      -> POST /event (narration to the dashboard) -> POST /action -> repeat.
Emulation only advances while actions run, so the game is effectively paused while Qwen thinks.

  qwen_red.py [--turns N] [--model qwen3.8:27b] [--think low|medium|high] [--server http://localhost:8765]
"""
import argparse
import base64
import hashlib
import io
import json
import os
import time

import requests
from PIL import Image

from milestones import MilestoneTracker, MILESTONES

HERE = os.path.dirname(os.path.abspath(__file__))
OLLAMA = os.environ.get("OLLAMA_HOST", "http://10.0.0.77:11434")
NOTES = os.path.join(HERE, "notes.md")
RUNS_DIR = os.path.join(HERE, "runs")

SYSTEM = """You are Qwen, a local AI playing Pokémon Red live on stream. You get the game state read from RAM, an ASCII walkability map, and a screenshot. Between turns the game does not advance, so take your time; but each turn only 1-6 button presses happen, so make them count.

How the game works: overworld movement is one tile per walk_X. Talk to people/signs with press_a while facing them. DOORS, STAIRS, and building entrances/exits are WARP tiles: you trigger them just by WALKING ONTO them, never with A. A warp tile often shows as `#` (blocked) on the ASCII map even though you can step onto it, so trust the screenshot for doors. IMPORTANT: if you keep re-entering the same building, it is because you are walking back onto its door tile — after leaving a building, step AWAY from the door (usually DOWN and to the side) before heading to your goal, or you will loop straight back inside. In menus and dialog, press_a advances/confirms, press_b cancels. Use a_until_dialog_end to skip through long text. ★The STATE does NOT report whether a dialog is open, so TRUST THE SCREENSHOT: if you see a text box, any sentence of text, or a ▼/▶ arrow at the bottom, a dialog IS open — clear it with a_until_dialog_end before anything else, and do not try to walk until it is gone. The title/intro screens need press_start then press_a. Name entry: choose a preset name when offered (press_a on it) instead of typing.

Map reading: the ASCII map is 10 columns (A-J) x 9 rows (1-9); you are @ at E5. `.` walkable, `#` blocked (but door/warp tiles read as `#` and are still steppable). A `~` tile looks walkable but is WALLED OFF from you — you cannot path there, so ignore it entirely (do not plan routes toward `~`). ★MOVEMENT RULE: you can only step a direction if the tile IMMEDIATELY next to `@` in that direction is `.`. If the tile directly ABOVE `@` is `#`, you CANNOT go north this turn regardless of what tiles further up look like — walk left or right along the wall to find the one `.` opening, then go up through it. up = row-1, down = row+1, left = col-1, right = col+1. Never plan a route through `#`. Doors and warps are usually on the edge of buildings; the map does not show them, use the screenshot.

Overall goal: beat the game. THE VERY FIRST STEP (you have no Pokémon yet): leave your house by walking onto the door at the bottom, then walk to the NORTH edge of Pallet Town toward the TALL GRASS on Route 1. Professor Oak runs out, stops you there, and walks you to his lab to pick a starter. You CANNOT enter Oak's lab or get a starter until this happens. So while you have no Pokémon, head NORTH to the grass at the top of town — do NOT keep entering buildings; your own house and the labs are dead ends until Oak intercepts you. After the starter: deliver Oak's parcel from Viridian City Mart back to Oak -> Pokédex -> Viridian Forest -> Pewter City gym (Brock). Heal at Pokémon Centers (talk to the nurse). Buy items at Marts.

Battle basics: in battle, press_a picks FIGHT, then a move; effective moves matter (Water beats Fire/Rock, Grass beats Water, Fire beats Grass/Bug, Electric beats Water). If HP is low and you have Potions, use ITEM. Run from wild battles you do not need.

If several turns pass with the same position and nothing changing, you are stuck: try a different direction, press_b to close a hidden menu, or read the screenshot again.

Available actions (strings, exactly): press_a, press_b, press_start, press_select, walk_up, walk_down, walk_left, walk_right, hold_a_30, wait_60, a_until_dialog_end.

Reply with JSON only:
{"thought": "<2-3 sentences: what you see, what you intend, why>",
 "actions": ["walk_up", "walk_up", "press_a"],
 "key_moment": "<optional: one line if something notable just happened (new town, badge, catch, starter)>",
 "notes": "<optional: rewrite your persistent notes (where you are, plan, lessons). Under 600 chars>"}
"""

SCHEMA = {
    "type": "object",
    "properties": {
        "thought": {"type": "string"},
        "actions": {"type": "array", "items": {"type": "string"}},
        "key_moment": {"type": "string"},
        "notes": {"type": "string"},
    },
    "required": ["thought", "actions"],
}
ALLOWED = {"press_a", "press_b", "press_start", "press_select", "walk_up", "walk_down", "walk_left",
           "walk_right", "hold_a_30", "wait_60", "a_until_dialog_end"}

# Provenance (BENCHMARK-SPEC.md §2b — same prompt, same rules, public receipts).
PROMPT_VERSION = "v2"          # bump whenever SYSTEM changes; old runs keep their version
HARNESS_VERSION = 1
NUM_CTX = 65536
TEMPERATURE = 0.6
PROMPT_SHA = hashlib.sha256(SYSTEM.encode()).hexdigest()[:16]


def compact(state):
    p = state.get("player", {}) or {}
    party = [f"{m.get('nickname')}({m.get('species')}) L{m.get('level')} HP {m.get('hp')}/{m.get('max_hp')}"
             + (f" {m.get('status')}" if m.get('status') else "") + " moves " + ",".join(
                 mv.get("name") if isinstance(mv, dict) else str(mv) for mv in m.get("moves", []))
             for m in state.get("party", []) or []]
    b = state.get("battle") or {}
    lines = [
        f"map: {(state.get('map') or {}).get('map_name')}  pos {p.get('position')}  facing {p.get('facing')}  money {p.get('money')}  badges {p.get('badges')}",
        "party: " + ("; ".join(party) if party else "none"),
        "bag: " + (", ".join(f"{i.get('item')}x{i.get('quantity')}" for i in state.get("bag", []) or []) or "empty"),
        f"in_battle: {b.get('in_battle')}",
    ]
    if b.get("in_battle"):
        lines.append("battle: " + json.dumps({k: v for k, v in b.items() if k != "in_battle"})[:400])
    fl = state.get("flags") or {}
    lines.append(f"flags: pokedex {fl.get('has_pokedex')}, parcel {fl.get('has_oaks_parcel')}, seen {fl.get('pokedex_seen')} owned {fl.get('pokedex_owned')}")
    return "\n".join(lines)


def screenshot_b64(server):
    png = requests.get(f"{server}/screenshot", timeout=15).content
    im = Image.open(io.BytesIO(png)).convert("RGB").resize((480, 432), Image.NEAREST)
    buf = io.BytesIO(); im.save(buf, "PNG")
    return base64.b64encode(buf.getvalue()).decode()


def ask(model, think, system, user, image_b64):
    r = requests.post(f"{OLLAMA}/api/chat", json={
        "model": model, "stream": False, "format": SCHEMA, "think": think, "keep_alive": "30m",
        "messages": [{"role": "system", "content": system},
                     {"role": "user", "content": user, "images": [image_b64]}],
        "options": {"num_ctx": NUM_CTX, "temperature": TEMPERATURE},
    }, timeout=600)
    r.raise_for_status()
    body = r.json()
    msg = body["message"]
    tokens = {"prompt": body.get("prompt_eval_count", 0), "completion": body.get("eval_count", 0)}
    return json.loads(msg["content"]), msg.get("thinking", ""), tokens


def event(server, typ, **kw):
    try:
        requests.post(f"{server}/event", json={"type": typ, **kw}, timeout=10)
    except Exception:
        pass


def write_summary(artifact_dir, run_id, model, run_name, think, tracker, turns_used, budget,
                  tokens, wall_s, notes, in_game_name="", rival_name=""):
    """Emit the per-run scoring + provenance JSON the leaderboard reads (BENCHMARK-SPEC.md §2/§2b)."""
    summary = {
        "run_id": run_id, "model": model, "provider": "ollama-local", "family": "qwen",
        "run_name": run_name,
        # the name the model gave itself / its rival in-game (personality for the card)
        "in_game_name": in_game_name, "rival_name": rival_name,
        # --- provenance / receipts ---
        "prompt_version": PROMPT_VERSION, "prompt_sha": PROMPT_SHA,
        "harness_version": HARNESS_VERSION, "execution_route": "ollama-local",
        "think_level": think, "num_ctx": NUM_CTX, "temperature": TEMPERATURE,
        "allowed_actions": sorted(ALLOWED),
        "run_date": time.strftime("%Y-%m-%d"), "model_release_date": None,  # filled via models.yaml (phase 2)
        "model_params": "27B", "quant": "Q4_K_M",
        "artifacts": {"log": "log.jsonl", "save_state": run_id},
        "notes": notes,
        # --- scoring ---
        "budget_turns": budget, "turns_used": turns_used, "wall_time_s": round(wall_s, 1),
        "tokens_in": tokens["prompt"], "tokens_out": tokens["completion"],
        "cost_usd": 0.0,  # local; provider adapters set real cost in phase 2
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


def build_map(state):
    """Render the walkability grid with unreachable-but-walkable tiles flagged `~`
    (flood-fill from the player), so the model never trusts a `.` it cannot reach."""
    c = state.get("collision") or {}
    grid = c.get("walkable")
    cell = c.get("player_cell") or "E5"
    if not grid:
        return None
    rows, cols = len(grid), len(grid[0])
    pc = ord(cell[0].upper()) - ord("A"); pr = int(cell[1:]) - 1
    reach = [[False] * cols for _ in range(rows)]
    if 0 <= pr < rows and 0 <= pc < cols and grid[pr][pc]:
        stack = [(pr, pc)]; reach[pr][pc] = True
        while stack:
            r, cc = stack.pop()
            for dr, dc in ((1,0),(-1,0),(0,1),(0,-1)):
                nr, nc = r+dr, cc+dc
                if 0 <= nr < rows and 0 <= nc < cols and grid[nr][nc] and not reach[nr][nc]:
                    reach[nr][nc] = True; stack.append((nr, nc))
    out = ["   " + " ".join(chr(ord("A")+x) for x in range(cols))]
    for r in range(rows):
        line = []
        for cc in range(cols):
            if (r, cc) == (pr, pc): line.append("@")
            elif not grid[r][cc]: line.append("#")
            elif reach[r][cc]: line.append(".")
            else: line.append("~")
        out.append(f"{r+1:2d} " + " ".join(line))
    out.append("@ you  . reachable  ~ walkable but WALLED OFF from you (cannot path there)  # blocked")
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
    args = ap.parse_args()
    S = args.server

    tracker = MilestoneTracker()
    run_start = time.time()
    tok = {"prompt": 0, "completion": 0}
    turn = 0
    run_id = f"{args.model.replace(':', '-').replace('.', '-')}-{time.strftime('%Y%m%d_%H%M%S')}"
    artifact_dir = os.path.join(RUNS_DIR, run_id)
    os.makedirs(artifact_dir, exist_ok=True)
    log_path = os.path.join(artifact_dir, "log.jsonl")
    print(f"run artifacts -> {artifact_dir}  (prompt {PROMPT_VERSION}/{PROMPT_SHA}, ctx {NUM_CTX})", flush=True)

    # Register a fresh tracked game session: boots the emulator clean AND makes the
    # dashboard's turn/action counters increment (/action only counts with an active
    # session) and gives the stream timer a server-side created_at anchor.
    run_label = args.run_name or run_id
    try:
        requests.post(f"{S}/games/new", json={"name": run_label}, timeout=45)
        print(f"registered game session '{run_label}' (fresh boot)", flush=True)
    except Exception as e:
        print(f"WARN: /games/new failed ({e}); counters/timer may not populate", flush=True)
    # /games/new leaves control at its default; ensure the loop is allowed to run.
    try:
        requests.post(f"{S}/control", json={"state": "running"}, timeout=10)
    except Exception:
        pass

    notes = open(NOTES).read() if os.path.exists(NOTES) else "(no notes yet)"
    history = []
    last_pos = None; same_pos = 0
    in_game_name = ""; rival_name = ""  # captured once she names herself / the rival
    for turn in range(1, args.turns + 1):
        try:
            ctl = requests.get(f"{S}/control", timeout=10).json().get("state", "running")
        except Exception:
            ctl = "running"
        if ctl == "paused":
            time.sleep(3); continue
        if ctl == "stopped":
            print("control = stopped, exiting"); break

        try:
            state = requests.get(f"{S}/state", timeout=15).json()
            amap_raw = requests.get(f"{S}/map/ascii", timeout=15).text
            img = screenshot_b64(S)
            amap = build_map(state) or amap_raw
        except Exception as e:
            print(f"[turn {turn}] server not reachable ({e}); retrying"); time.sleep(5); continue
        pos = ((state.get("map") or {}).get("map_id"), json.dumps((state.get("player") or {}).get("position")))
        same_pos = same_pos + 1 if pos == last_pos else 0
        last_pos = pos
        _pl = state.get("player") or {}
        if _pl.get("name"): in_game_name = _pl["name"]
        if _pl.get("rival_name"): rival_name = _pl["rival_name"]
        before = set(tracker.first_turn)
        tracker.update(state, turn)
        newly = [(k, l) for k, l, _ in MILESTONES if k in tracker.first_turn and k not in before]
        for key, label in newly:
            print(f"🏁 MILESTONE: {label} (turn {turn})", flush=True)
            event(S, "key_moment", description=f"Milestone: {label}", category="milestone")
        if "beat_brock" in tracker.first_turn:
            print(f"🏆 Brock defeated at turn {turn} — ceiling reached, ending run.", flush=True)
            break
        stuck = f"\nWARNING: position unchanged for {same_pos} turns. Do something different." if same_pos >= 3 else ""
        user = (f"NOTES:\n{notes}\n\nRECENT TURNS:\n" + "\n".join(history[-12:]) +
                f"\n\nSTATE:\n{compact(state)}\n\nWALKABILITY MAP (you are @ at E5):\n{amap}{stuck}\n\nThe screenshot is attached. Take your turn.")
        t0 = time.time()
        try:
            plan, thinking, tokens = ask(args.model, args.think, SYSTEM, user, img)
        except Exception as e:
            print(f"[turn {turn}] model error: {e}"); time.sleep(5); continue
        dt = time.time() - t0
        tok["prompt"] += tokens["prompt"]; tok["completion"] += tokens["completion"]
        thought = (plan.get("thought") or "").strip()
        actions = [a for a in plan.get("actions", []) if a in ALLOWED][:6] or ["wait_60"]
        print(f"\n=== turn {turn} | {compact(state).splitlines()[0]} | model {dt:.0f}s ===", flush=True)
        print(f"💭 {thought}", flush=True)
        print(f"  ▶ {' '.join(actions)}", flush=True)
        event(S, "reasoning", text=thought)
        event(S, "decision", text=" ".join(actions))
        if plan.get("key_moment"):
            event(S, "key_moment", description=plan["key_moment"][:200], category="milestone")
        try:
            res = requests.post(f"{S}/action", json={"actions": actions}, timeout=120).json()
            result = f"executed {res.get('actions_executed')}"
        except Exception as e:
            result = f"action error: {e}"
        if plan.get("notes"):
            notes = plan["notes"][:600]; open(NOTES, "w").write(notes)
        mp = (state.get("map") or {}).get("map_name")
        pp = (state.get("player") or {}).get("position")
        history.append(f"turn {turn}: at {mp} {pp} did [{' '.join(actions)}] -> {result}")
        with open(log_path, "a") as f:
            f.write(json.dumps({"turn": turn, "state": compact(state), "thinking": thinking,
                                "plan": plan, "result": result, "model_s": dt,
                                "tokens": tokens}) + "\n")
        if turn % args.save_every == 0:
            try:
                requests.post(f"{S}/save", json={"name": run_id}, timeout=30)
            except Exception:
                pass

    final_notes = open(NOTES).read() if os.path.exists(NOTES) else ""
    write_summary(artifact_dir, run_id, args.model, args.run_name or "run", args.think, tracker,
                  turn, args.turns, tok, time.time() - run_start, final_notes,
                  in_game_name=in_game_name, rival_name=rival_name)


if __name__ == "__main__":
    main()
