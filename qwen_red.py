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
OLLAMA = os.environ.get("OLLAMA_HOST", "http://<server-host>:11434")
RUNS_DIR = os.path.join(HERE, "runs")

SYSTEM = """You are Qwen, a local AI playing Pokémon Red live on stream. You get the game state read from RAM, an ASCII walkability map, and a screenshot. The game keeps running in real time between turns (NPCs move, animations finish), so the screenshot is a moment in time; each turn only 1-6 button presses happen, so make them count.

How the game works: overworld movement is one tile per walk_X. Talk to people/signs with press_a while facing them. DOORS, STAIRS, and building entrances/exits are WARP tiles: you trigger them just by WALKING ONTO them, never with A. Every warp tile is marked on the ASCII map (read from the game's own warp table): `D` = a door that leads OUTSIDE (a building's entrance from the street, or its exit mat from inside), `S` = stairs or a passage to a DIFFERENT indoor map (the other floor, a gate, a cave). So a `.` is NEVER a door, a `D` is the ONLY way in or out of a building, and an `S` NEVER takes you outside: if you are inside and want the street, ignore every `S` and find the `D`. IMPORTANT: after leaving a building you stand directly BELOW its `D`; walking up re-enters it. Step away sideways first, then head to your goal. In menus and dialog, press_a advances/confirms, press_b cancels. Use a_until_dialog_end to skip through long text. ★SCREEN TEXT below is exactly what is written on screen right now, read from the game's memory. If a text box is open, READ IT FIRST: people tell you what to do next (if someone says "don't leave yet", stay and talk to them; if the text names a place or a person, that is your lead). Then clear the box with a_until_dialog_end; whatever it skipped past is quoted back to you in RECENT TURNS. You cannot walk while a text box is open. The title/intro screens need press_start then press_a. Name entry: choose a preset name when offered (press_a on it) instead of typing.

Map reading: the ASCII map is 10 columns (A-J) x 9 rows (1-9); you are @ at E5. The grid is a WINDOW that moves with you: E5 is always your current STATE position (x,y), so grid letters/rows are NOT world coordinates (column A = x-4, J = x+5; row 1 = y-4, row 9 = y+4) and E5 never disagrees with STATE. `.` walkable, `#` blocked, `D` door to outside / `S` stairs or passage to another indoor map: outdoor doors and stairs trigger the moment you step onto them, but the EXIT MAT inside a building (the `D` tiles on its bottom wall) does not: stand on it and walk_down once more, into the wall, to go outside (test: sidestepping between the two mat tiles does nothing), `v` a ledge: walk_down from the tile above it hops you over to the tile below; you can never go back up through it. ★MOVEMENT RULE: you can only step a direction if the tile IMMEDIATELY next to `@` in that direction is `.`, `D`, `S`, or (going down only) `v`. If the tile directly ABOVE `@` is `#`, you CANNOT go north this turn regardless of what tiles further up look like — walk left or right along the wall to find the one `.` opening, then go up through it. up = row-1, down = row+1, left = col-1, right = col+1. Never plan a route through `#`. To enter a building, walk onto its `D`. Your memory of the Gen 1 maps is unreliable: treat any recalled layout ('the stairs are bottom-left', 'the Pokémon Center is north') as a guess until the map or screenshot confirms it.

Overall goal: beat the game. The opening runs in a fixed order, and the game will not let you skip a step. Where you are in it is visible in STATE (party, parcel flag, pokedex flag): (1) No Pokémon yet: your house and the lab are dead ends. Walk to the NORTH edge of Pallet Town toward the tall grass; Professor Oak stops you there and walks you to his lab, where you pick a starter and fight your rival. (2) Starter but no parcel and no Pokédex: Oak has nothing more for you yet. Leave Pallet NORTH through Route 1 to Viridian City; the clerk in the Viridian Mart hands you Oak's parcel. (3) Parcel in your bag: go back SOUTH down Route 1 to Oak's lab and give it to him; he gives you the Pokédex. (4) Pokédex: north again to Viridian, then Route 2 -> Viridian Forest -> Pewter City -> Brock's gym. Heal at Pokémon Centers (talk to the nurse). Buy Potions and Poké Balls at Marts.

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
PROMPT_VERSION = "v11"          # bump whenever SYSTEM changes; old runs keep their version
HARNESS_VERSION = 2
NUM_CTX = 65536
TEMPERATURE = 0.6
NUM_PREDICT = 8192          # ceiling on thinking+answer tokens per turn; a runaway ends in ~1 min, not the 600s timeout
PROMPT_SHA = hashlib.sha256(SYSTEM.encode()).hexdigest()[:16]


def compact(state):
    p = state.get("player", {}) or {}
    party = [f"{m.get('nickname')}({m.get('species')}) L{m.get('level')} HP {m.get('hp')}/{m.get('max_hp')}"
             + (f" {m.get('status')}" if m.get('status') else "") + " moves " + ",".join(
                 mv.get("name") if isinstance(mv, dict) else str(mv) for mv in m.get("moves", []))
             for m in state.get("party", []) or [] if m.get("level")]  # a slot mid-initialization reads ??? L0 HP 0/0
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


def shrink_png(png_bytes: bytes) -> str:
    im = Image.open(io.BytesIO(png_bytes)).convert("RGB").resize((480, 432), Image.NEAREST)
    buf = io.BytesIO(); im.save(buf, "PNG")
    return base64.b64encode(buf.getvalue()).decode()


def ask(model, think, system, user, image_b64):
    r = requests.post(f"{OLLAMA}/api/chat", json={
        "model": model, "stream": False, "format": SCHEMA, "think": think, "keep_alive": "30m",
        "messages": [{"role": "system", "content": system},
                     {"role": "user", "content": user, "images": [image_b64]}],
        "options": {"num_ctx": NUM_CTX, "temperature": TEMPERATURE, "num_predict": NUM_PREDICT},
    }, timeout=600)
    r.raise_for_status()
    body = r.json()
    msg = body["message"]
    tokens = {"prompt": body.get("prompt_eval_count", 0), "completion": body.get("eval_count", 0)}
    return msg["content"], msg.get("thinking", ""), tokens


def event(server, typ, **kw):
    try:
        requests.post(f"{server}/event", json={"type": typ, **kw}, timeout=10)
    except Exception:
        pass


def write_summary(artifact_dir, run_id, model, run_name, think, tracker, turns_used, budget,
                  tokens, wall_s, notes, in_game_name="", rival_name="", frames_saved=True, acts=None):
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
        "run_id": run_id, "model": model, "provider": "ollama-local", "family": "qwen",
        "run_name": run_name,
        # the name the model gave itself / its rival in-game (personality for the card)
        "in_game_name": in_game_name, "rival_name": rival_name,
        # --- provenance / receipts ---
        "prompt_version": PROMPT_VERSION, "prompt_sha": PROMPT_SHA,
        "harness_version": HARNESS_VERSION, "execution_route": "ollama-local",
        "harness_git_sha": harness_git_sha, "harness_files_sha": harness_files_sha, "frames_saved": frames_saved,
        "think_level": think, "num_ctx": NUM_CTX, "temperature": TEMPERATURE, "num_predict": NUM_PREDICT,
        "allowed_actions": sorted(ALLOWED),
        "run_date": time.strftime("%Y-%m-%d"), "model_release_date": None,  # filled via models.yaml (phase 2)
        "model_params": "27B", "quant": "Q4_K_M",
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


def build_map(state, warps=()):
    """Render the walkability grid; walkable tiles with no route from the player (flood-fill)
    render as `#`, so the model never trusts a `.` it cannot reach. Warp tiles (doors, stairs) from
    the game's warp table render as `D` (test run 4: a door shown as `.` cost ~95 turns of re-entering home)."""
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
    ids = c.get("tile_ids") or []
    ledge_down = set()
    if c.get("tileset") == 0 and ids:  # overworld tileset: 0x36/0x37 are the one-way ledge tiles you hop DOWN over
        for r in range(rows):
            for cc in range(cols):
                if r < len(ids) and cc < len(ids[r]) and ids[r][cc] in (0x36, 0x37):
                    ledge_down.add((r, cc))
    if ledge_down:  # a hop carries you from the tile above the ledge to the tile below it
        for r, cc in sorted(ledge_down):
            if r - 1 >= 0 and reach[r - 1][cc] and r + 1 < rows and grid[r + 1][cc] and not reach[r + 1][cc]:
                reach[r + 1][cc] = True
                stack = [(r + 1, cc)]
                while stack:
                    rr, c2 = stack.pop()
                    for dr, dc in ((1,0),(-1,0),(0,1),(0,-1)):
                        nr, nc = rr+dr, c2+dc
                        if 0 <= nr < rows and 0 <= nc < cols and grid[nr][nc] and not reach[nr][nc]:
                            reach[nr][nc] = True; stack.append((nr, nc))
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
            elif (r, cc) in doors: line.append("D")
            elif (r, cc) in stairs: line.append("S")
            elif (r, cc) in ledge_down: line.append("v")
            elif not grid[r][cc]: line.append("#")
            elif reach[r][cc]: line.append(".")
            else: line.append("#")  # RAM says walkable but no route from @ (fenced/ledged off): show it as blocked, she treated `~` as a target (v4)
        out.append(f"{r+1:2d} " + " ".join(line))
    out.append("@ you  . reachable  # blocked  D door to OUTSIDE  S stairs/passage to another indoor map (never outside)  v ledge (hop DOWN over it; one-way)")
    if (pr, pc) in doors and not outdoors:
        out.append("★ YOU ARE STANDING ON THE EXIT MAT (a D is under @). walk_down once more to go outside.")
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
    args = ap.parse_args()
    S = args.server

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
            requests.post(f"{S}/run_meta", json={"model": args.model, "think": args.think, "ctx": NUM_CTX,
                                                 "route": "local", "prompt_version": PROMPT_VERSION}, timeout=10)
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
            frame = requests.get(f"{S}/frame", timeout=20).json()
            state = frame["state"]
            amap = build_map(state, frame.get("warps") or ()) or frame.get("ascii") or "(no map: in battle or menu)"
            screen_text = frame.get("screen_text") or "(nothing written on screen)"
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
            print(f"[turn {turn}] server not reachable ({e}); retrying"); time.sleep(5); continue
        pos = ((state.get("map") or {}).get("map_id"), json.dumps((state.get("player") or {}).get("position")))
        ui_now = (frame.get("screen_text") or "") != "" or ((state.get("battle") or {}).get("in_battle"))
        same_pos = 0 if ui_now else (same_pos + 1 if pos == last_pos else 0)  # menus/dialog/battle do not move you
        last_pos = pos
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
        stuck = f"\nWARNING: position unchanged for {same_pos} turns. Do something different." if same_pos >= 3 else ""
        user = (f"YOUR PRIOR NOTES (you wrote these on earlier turns; they are plans and guesses, NOT verified observations — the STATE, map and screenshot below are the truth):\n{notes}\n\nRECENT TURNS:\n" + "\n".join(history[-12:]) +
                f"\n\nSTATE:\n{compact(state)}\n\nSCREEN TEXT (words on screen right now):\n{screen_text}\n\nWALKABILITY MAP (you are @ at E5):\n{amap}{stuck}\n\nThe screenshot is attached. Take your turn.")
        t0 = time.time()
        retried = False
        try:
            content_str, thinking, tokens = ask(args.model, args.think, SYSTEM, user, img)
            if not content_str.strip():
                # Ollama structured output sometimes ends the reply inside the thinking and returns empty content
                # (test run 3: T19, T31; local smoke T2). A serving glitch, not a decision: one retry, logged.
                retried = True
                c2, th2, tk2 = ask(args.model, args.think, SYSTEM, user, img)
                tokens = {"prompt": tokens["prompt"] + tk2["prompt"], "completion": tokens["completion"] + tk2["completion"]}
                content_str, thinking = c2, (thinking + "\n---retry---\n" + th2)
        except Exception as e:
            with open(log_path, "a") as f:
                f.write(json.dumps({"turn": turn, "prompt_version": PROMPT_VERSION, "model_error": str(e), "user_message": user, "screenshot_sha256": screenshot_sha256}) + "\n")
            print(f"[turn {turn}] model error: {e}"); time.sleep(5); continue
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
        steps = []; start = end = pose_of(state); tail_parts = []
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
                tail_parts.append(" (menu/dialog input, position unchanged)" if ui_turn and steps else " (no movement)")
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
                tail_parts.append(' said: "' + " | ".join(pages)[:1500] + '"')  # 400 cut Oak's "you can have one! Choose!" (run 4 T62)
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
            f.write(json.dumps({"turn": turn, "prompt_version": PROMPT_VERSION, "user_message": user, "screenshot_sha256": screenshot_sha256, "frame_file": frame_file, "state": state, "screen_text": screen_text, "thinking": thinking, "plan": plan, "plan_actions_raw": plan_actions_raw, "actions": actions, "fallback_reason": fallback_reason, "steps": steps, "result": result_tail, "model_s": dt, "tokens": tokens, "retried": retried}) + "\n")
        if turn % args.save_every == 0:
            try:
                requests.post(f"{S}/save", json={"name": run_id}, timeout=30)
            except Exception:
                pass

    final_notes = open(notes_path).read() if os.path.exists(notes_path) else ""
    write_summary(artifact_dir, run_id, args.model, args.run_name or "run", args.think, tracker,
                  turn, args.turns, tok, time.time() - run_start, final_notes,
                  in_game_name=in_game_name, rival_name=rival_name, frames_saved=not args.no_frames, acts=acts)


if __name__ == "__main__":
    main()
