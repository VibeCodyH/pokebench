#!/usr/bin/env python3
"""Run a models.yaml entry through the shared Pokémon Red benchmark harness.

    .venv/bin/python run_benchmark.py --model-key 'qwen3.8:27b'

Imports make no requests. The game must already exist and /control must be running
(run.sh handles that). Notes and artifacts start fresh for each invocation.
"""

import argparse
import base64
import hashlib
import json
import math
import os
import re
import subprocess
import tempfile
import time

import requests
import yaml

from milestones import MILESTONES, MilestoneTracker
from providers import get_provider
from qwen_red import (
    ALLOWED,
    HARNESS_VERSION,
    HERE,
    NUM_CTX,
    PROMPT_SHA,
    PROMPT_VERSION,
    RUNS_DIR,
    SCHEMA,
    render_system,
    resolve_identity,
    TEMPERATURE,
    build_map,
    compact,
    event,
    shrink_png,
)


def load_model(model_key, registry_path=None):
    """Load one registry row; context is the registry's alias for num_ctx."""
    with open(registry_path or os.path.join(HERE, "models.yaml")) as source:
        registry = yaml.safe_load(source)
    rows = registry.get("models") if isinstance(registry, dict) else None
    if not isinstance(rows, list) or not all(isinstance(row, dict) for row in rows):
        raise ValueError("models.yaml must contain a models list of mappings")
    matches = [row for row in rows if row.get("key") == model_key]
    if len(matches) != 1:
        keys = ", ".join(str(row.get("key")) for row in rows)
        raise ValueError(f"Expected one registry entry for {model_key!r}; available: {keys}")
    model = dict(matches[0])
    for field in ("provider", "api_model_id", "family"):
        if not isinstance(model.get(field), str) or not model[field].strip():
            raise ValueError(f"{model_key}: {field} must be a nonempty string")
    model["provider"] = model["provider"].strip().lower()
    model.setdefault("think", "low")
    if not isinstance(model["think"], str):
        raise ValueError(f"{model_key}: think must be a string (quote 'off' in YAML)")
    model["num_ctx"] = model.get("num_ctx", model.get("context", NUM_CTX))
    if type(model["num_ctx"]) is not int or model["num_ctx"] <= 0:
        raise ValueError(f"{model_key}: context/num_ctx must be a positive integer")
    # Optional cap on the model's own output. Absent or null means the adapter's default,
    # which is 8192 for the hosted APIs; thinking models spend that on reasoning and get
    # truncated mid-plan, so they need a bigger ceiling than the default.
    max_out = model.get("max_output_tokens")
    if max_out is not None and (type(max_out) is not int or max_out <= 0):
        raise ValueError(f"{model_key}: max_output_tokens must be a positive integer")
    model.setdefault("temperature", TEMPERATURE)
    temperature = model["temperature"]
    if (type(temperature) not in (int, float)
            or not math.isfinite(temperature) or temperature < 0):
        raise ValueError(f"{model_key}: temperature must be finite and nonnegative")
    # PyYAML also accepts unquoted ISO dates, which it loads as date objects.
    release = model.get("release_date")
    if hasattr(release, "isoformat"):
        model["release_date"] = release.isoformat()
    return model


def make_provider(model):
    """Pass only settings supported by the existing adapter constructors."""
    opts = {name: model.get(name) for name in (
        "input_cost_per_mtok", "output_cost_per_mtok",
    )}
    # Only when set: the adapters' own defaults differ, and None would override them.
    if model.get("max_output_tokens") is not None:
        opts["max_tokens"] = model["max_output_tokens"]
    if model["provider"] == "ollama":
        opts["num_ctx"] = model["num_ctx"]
    if model["provider"] in {"ollama", "google"}:
        opts["temperature"] = model["temperature"]
    provider = get_provider(model["provider"], model["api_model_id"], **opts)
    # Reject missing hosted rates before starting a run, rather than at summary time.
    provider.cost({"prompt": 0, "completion": 0})
    return provider


def harness_fingerprint():
    """Git SHA + a hash over every file that defines run behavior or scoring. Call at run
    START so a mid-run edit can't mislabel the code the process actually loaded."""
    try:
        git_sha = subprocess.check_output(
            ["git", "-C", HERE, "rev-parse", "--short", "HEAD"], text=True, timeout=5).strip()
    except Exception:  # container has no .git: deploy drops the sha in env or a GIT_SHA file
        git_sha = os.environ.get("POKEBENCH_GIT_SHA")
        if not git_sha and os.path.exists(os.path.join(HERE, "GIT_SHA")):
            git_sha = open(os.path.join(HERE, "GIT_SHA")).read().strip() or None
    try:
        blob = b""
        for name in ("milestones.py", "providers.py", "run_benchmark.py", "qwen_red.py", "serve_live.py"):
            blob += open(os.path.join(HERE, name), "rb").read()
        files_sha = hashlib.sha256(blob).hexdigest()[:16]
    except Exception:
        files_sha = None
    return git_sha, files_sha


def write_summary(artifact_dir, run_id, model, provider, run_name, tracker,
                  turns_used, budget, tokens, wall_s, notes, save_name,
                  harness_git_sha=None, harness_files_sha=None, blackouts=(),
                  termination="budget", failed_attempts=None):
    """The qwen_red.write_summary JSON keys, with registry/adapter provenance."""
    provider_name = model["provider"]
    summary = {
        "run_id": run_id,
        "model": model["api_model_id"],
        "provider": provider_name,
        "family": model["family"],
        "run_name": run_name,
        "prompt_version": PROMPT_VERSION,
        "prompt_sha": PROMPT_SHA,
        "harness_version": HARNESS_VERSION,
        "harness_git_sha": harness_git_sha,
        "harness_files_sha": harness_files_sha,
        # the model's actual output ceiling, recorded so it can't drift from the setting a run claims
        "max_output_tokens": getattr(provider, "max_tokens", None),
        "execution_route": "ollama-local" if provider_name == "ollama" else f"{provider_name}-api",
        "think_level": model["think"],
        "num_ctx": model["num_ctx"],
        # Anthropic/OpenAI adapters leave temperature at the API default.
        "temperature": model["temperature"] if provider_name in {"ollama", "google"} else None,
        "allowed_actions": sorted(ALLOWED),
        "run_date": time.strftime("%Y-%m-%d"),
        "model_release_date": model.get("release_date"),
        "model_params": model.get("params"),
        "quant": model.get("quant"),
        "artifacts": {"log": "log.jsonl", "save_state": save_name},
        "notes": notes,
        "budget_turns": budget,
        "turns_used": turns_used,  # completed turns only: an attempt cut short by SIGINT is not a turn
        # budget | beat_brock | interrupted | stopped | provider_error — a partial run is never a scored result
        "termination_reason": termination,
        "wall_time_s": round(wall_s, 1),
        "tokens_in": tokens["prompt"],
        "tokens_out": tokens["completion"],
        # retried attempts (bad JSON, refusals, empty replies): work the model did that tokens_in/out exclude
        "failed_attempts": dict(failed_attempts or {"count": 0, "prompt": 0, "completion": 0}),
        "cost_usd": provider.cost(tokens),
        "youtube_url": None,
        "timestamp": time.strftime("%Y%m%d_%H%M%S"),
        "blackouts": list(blackouts),  # turns the party whited out (leaderboard replay drops a skull there)
        **tracker.summary(),
    }
    path = os.path.join(artifact_dir, "summary.json")
    with open(path, "x") as output:
        json.dump(summary, output, indent=2)
    print(f"\n=== RUN SUMMARY -> {path} ===", flush=True)
    cost = summary["cost_usd"]
    cost_str = f"${cost:.6f}" if isinstance(cost, (int, float)) else "$? (rates unset)"
    print(f"furthest: {summary['furthest_label']} (idx {summary['furthest_index']}) | "
          f"turns {turns_used}/{budget} | tok in/out {tokens['prompt']}/{tokens['completion']} | "
          f"{cost_str} | {wall_s:.0f}s", flush=True)
    return path


def record_milestones(server, tracker, state, turn):
    before = set(tracker.first_turn)
    tracker.update(state, turn)
    for key, label, _ in MILESTONES:
        if key in tracker.first_turn and key not in before:
            print(f"🏁 MILESTONE: {label} (turn {turn})", flush=True)
            event(server, "key_moment", description=f"Milestone: {label}", category="milestone")
            try:  # feed the dashboard JOURNEY tracker; summary.json is the scoring source of truth
                requests.post(f"{server}/milestones", json={"key": key, "label": label, "turn": turn}, timeout=10)
            except Exception:
                pass
    return "beat_brock" in tracker.first_turn


def save_game(server, name):
    """Save names are unique to the run; the server owns the actual save file."""
    try:
        response = requests.post(f"{server}/save", json={"name": name}, timeout=30)
        response.raise_for_status()
        if response.json().get("success"):
            return name
    except Exception as exc:
        print(f"save error: {exc}", flush=True)
    return None


# Headroom (tokens) reserved on top of the measured text so the assembled request — system,
# notes, state, map, screenshot, and the model's own output — never overflows the context.
# A 480x432 PNG costs well under 1600 tokens on every provider we run; 16384 covers the
# largest output allowance.
_IMAGE_TOKENS = 1600
_OUTPUT_TOKENS = 16384
_SAFETY_TOKENS = 1024
# How many milestone spans of history to keep. Anchor the prompt window at the start of the
# Nth-from-newest milestone reached and drop everything older: stale pre-objective context
# (Pallet, Route 1) falls away while the CURRENT objective's full trail is retained, so a
# model's own loop evidence (revisiting the same tile) stays intact. fit_recent still caps
# the result at num_ctx, bounding cost when a model is stuck at one milestone for many turns.
MILESTONE_WINDOW = 2
# Provider-error policy: abort on auth/billing bodies, back off 5s→300s, give up after this many
# seconds of consecutive failures. Billing 429s look like rate limits by status; only the body tells.
ERROR_WINDOW = 1800
BILLING_WORDS = ("credits are depleted", "credit balance", "prepay", "insufficient_quota", "insufficient quota")


def milestone_anchor_turn(tracker, keep):
    """Turn to start the prompt window at: the first-hit turn of the keep-th milestone from
    the newest one reached. Fewer than `keep` milestones reached -> 0 (keep all history).
    furthest_index is monotonic, so regressing off a milestone never moves the anchor back."""
    recorded = [MILESTONES[i][0] for i in range(len(MILESTONES))
                if MILESTONES[i][0] in tracker.first_turn]
    if len(recorded) < keep:
        return 0
    return tracker.first_turn[recorded[-keep]]


def pose_of(st):
    sm = st.get("map") or {}
    sp = (st.get("player") or {}).get("position") or {}
    return {"map_id": sm.get("map_id"), "map_name": sm.get("map_name"), "pos": [sp.get("x"), sp.get("y")],
            "loaded": sm.get("loaded", True)}


def fmt_pose(p):
    if p.get("loaded", True) is False:
        return "no map (title/intro)"
    pos = p.get("pos") or [None, None]
    return f"{p.get('map_name') or 'Unknown'} ({pos[0]},{pos[1]})"


def fit_recent(history, num_ctx, static_chars):
    """Newest whole history entries that fit the model's context after reserving room for the
    rest of the request. Keeps a chronological suffix; returns [] when nothing fits — never the
    whole list, which a bare history[-0:] slice would wrongly return."""
    reserve = _IMAGE_TOKENS + _OUTPUT_TOKENS + _SAFETY_TOKENS + -(-static_chars // 4)
    budget_chars = max(0, num_ctx - reserve) * 4  # ~4 chars/token, conservative
    kept, used = [], 0
    for line in reversed(history):
        used += len(line) + 1
        if used > budget_chars:
            break
        kept.append(line)
    kept.reverse()
    return kept


def run(model, provider, server, budget=1000, run_name="run", no_frames=False):
    server = server.rstrip("/")
    os.makedirs(RUNS_DIR, exist_ok=True)
    slug = re.sub(r"[^A-Za-z0-9_-]+", "-", model["key"]).strip("-")[:80] or "model"
    prefix = f"{slug}-{time.strftime('%Y%m%d_%H%M%S')}-"
    artifact_dir = tempfile.mkdtemp(prefix=prefix, dir=RUNS_DIR)
    if not no_frames:
        os.makedirs(os.path.join(artifact_dir, "frames"))
    run_id = os.path.basename(artifact_dir)
    log_path = os.path.join(artifact_dir, "log.jsonl")
    notes_path = os.path.join(artifact_dir, "notes.md")
    with open(log_path, "x"):
        pass
    print(f"run artifacts -> {artifact_dir}  (prompt {PROMPT_VERSION}/{PROMPT_SHA}, "
          f"ctx {model['num_ctx']})", flush=True)

    tracker = MilestoneTracker()
    run_start = time.time()
    harness_git_sha, harness_files_sha = harness_fingerprint()  # snapshot the code at run start
    try:  # tell the /stream dashboard which model is playing (branding, colors, ctx label)
        requests.post(f"{server}/run_meta", json={
            "model": model["api_model_id"], "display_name": model.get("display_name") or "", "think": model["think"], "ctx": model["num_ctx"],
            "route": ("local" if model["provider"] == "ollama" else "api"),
            "prompt_version": PROMPT_VERSION,
        }, timeout=10)
    except Exception:
        pass
    total_tokens = {"prompt": 0, "completion": 0}
    notes = ""
    history = []
    history_turns = []  # turn number per history entry (turns can be skipped)
    name = model.get("display_name")
    identity = (f"You are {name}, an AI playing Pokémon Red live on stream." if name
                else resolve_identity(model["api_model_id"], model["provider"]))
    system_prompt = render_system(identity)
    turn = 0
    turns_done = 0  # turns whose plan reached the emulator; `turn` may be one ahead mid-attempt
    termination = "budget"
    failed_attempts = {"count": 0, "prompt": 0, "completion": 0}  # retried model calls: usage the totals exclude
    save_name = None
    acted = False
    blackouts = []
    errors_in_a_row = 0
    first_error_at = None
    try:
        # A turn is one model plan that reached the emulator. Pauses, server hiccups and
        # provider errors retry the same turn number so outages never eat the model's budget.
        while turn < budget:
            turn += 1
            try:
                control = requests.get(f"{server}/control", timeout=10).json().get("state", "running")
            except Exception:
                control = "running"
            if control == "paused":
                turn -= 1
                time.sleep(3)
                continue
            if control == "stopped":
                print("control = stopped, exiting", flush=True)
                termination = "stopped"
                break

            try:
                frame = requests.get(f"{server}/frame", timeout=20).json()
                state = frame["state"]  # one snapshot: state, warps, screen_text, screenshot all agree
                screen_text = frame.get("screen_text") or "(nothing written on screen)"
                # Warps render exit/door tiles as D/S (a door shown as a plain . once cost ~95 turns);
                # a text box overwrites tilemap rows and paints false # walls, so hide the map instead.
                if frame.get("dialog_open") or frame.get("screen_text"):
                    amap = "(map hidden while text is on screen)"
                elif frame.get("settle") == "capped":
                    amap = "(map hidden while frame is unsettled)"
                elif frame.get("menu_open") or frame.get("in_battle"):
                    amap = "(no map: in battle or menu)"
                else:
                    amap = build_map(state, frame.get("warps") or ()) or frame.get("ascii") or "(no map: in battle or menu)"
                img = shrink_png(base64.b64decode(frame["screenshot_b64"]))
            except Exception as exc:
                print(f"[turn {turn}] server not reachable ({exc}); retrying", flush=True)
                turn -= 1
                time.sleep(5)
                continue

            if record_milestones(server, tracker, state, turn):
                print(f"🏆 Brock defeated at turn {turn} — ceiling reached, ending run.", flush=True)
                termination = "beat_brock"
                break
            head = f"NOTES:\n{notes or '(no notes yet)'}\n\nRECENT TURNS:\n"
            tail = (f"\n\nSTATE:\n{compact(state)}\n\nSCREEN TEXT (words on screen right now):\n{screen_text}"
                    f"\n\nWALKABILITY MAP (you are @ at E5):\n{amap}"
                    "\n\nThe screenshot is attached. Take your turn.")
            anchor = milestone_anchor_turn(tracker, MILESTONE_WINDOW)
            windowed = [h for h, t in zip(history, history_turns) if t >= anchor]
            recent = fit_recent(windowed, model["num_ctx"], len(system_prompt) + len(head) + len(tail))
            user = head + "\n".join(recent) + tail
            frame_file = None
            if not no_frames:
                frame_file = f"frames/turn-{turn:04d}.png"
                with open(os.path.join(artifact_dir, frame_file), "wb") as output:
                    output.write(base64.b64decode(img))  # exactly the resized PNG passed to provider.chat
            observation = {"frame_file": frame_file, "collision": state.get("collision"),
                           "warps": frame.get("warps") or [], "party_count": len(state.get("party") or []),
                           "dialog_open": frame.get("dialog_open"), "menu_open": frame.get("menu_open"),
                           "map_loaded": frame.get("map_loaded", True),
                           "in_battle": frame.get("in_battle"), "settle": frame.get("settle")}
            started = time.time()
            try:
                plan, thinking, tokens = provider.chat(system_prompt, user, img, SCHEMA, model["think"])
            except Exception as exc:
                if frame_file:
                    # A retried turn gets the required canonical filename; preserve this failed
                    # request's image separately so its log record cannot point at a later PNG.
                    error_frame = frame_file[:-4] + f"-error-{time.time_ns()}.png"
                    os.rename(os.path.join(artifact_dir, frame_file), os.path.join(artifact_dir, error_frame))
                    observation["frame_file"] = error_frame
                response = getattr(exc, "response", None)
                status = getattr(response, "status_code", None)
                body = (getattr(response, "text", None) or "")[:500]
                usage = getattr(exc, "usage", None)  # adapters attach usage when the response arrived but the plan was bad
                failed_attempts["count"] += 1
                for key in ("prompt", "completion"):
                    failed_attempts[key] += int((usage or {}).get(key, 0))
                with open(log_path, "a") as output:
                    output.write(json.dumps({"turn": turn, "model_error": str(exc), "error_body": body,
                                             "raw_output": getattr(exc, "raw_output", None),
                                             "model_s": time.time() - started, "tokens": usage,
                                             "turn_not_counted": True, **observation}) + "\n")
                errors_in_a_row += 1
                first_error_at = first_error_at or time.time()
                # Auth and billing failures never clear on their own (a depleted-credits 429 once looped
                # 5,341 times overnight), and a provider that stays down past the window is not worth waiting on.
                billing = any(word in body.lower() for word in BILLING_WORDS)
                if status in (401, 402, 403) or billing:
                    print(f"[turn {turn}] non-retryable provider error {status}, aborting: {exc} {body}", flush=True)
                    termination = "provider_error"
                    break
                if time.time() - first_error_at > ERROR_WINDOW:
                    print(f"[turn {turn}] provider failing for {ERROR_WINDOW}s straight, aborting: {exc} {body}", flush=True)
                    termination = "provider_error"
                    break
                delay = min(5 * 2 ** (errors_in_a_row - 1), 300)
                print(f"[turn {turn}] model error: {exc} {body}; retrying the same turn in {delay}s", flush=True)
                turn -= 1
                time.sleep(delay)
                continue
            errors_in_a_row = 0
            first_error_at = None
            elapsed = time.time() - started
            for key in total_tokens:
                total_tokens[key] += tokens[key]
            thought = str(plan.get("thought") or "").strip()
            proposed = plan.get("actions")
            actions = ([action for action in proposed if isinstance(action, str) and action in ALLOWED][:6]
                       if isinstance(proposed, list) else []) or ["wait_60"]
            print(f"\n=== turn {turn} | {compact(state).splitlines()[0]} | model {elapsed:.0f}s ===", flush=True)
            print(f"💭 {thought}\n  ▶ {' '.join(actions)}", flush=True)
            event(server, "reasoning", text=thought)
            event(server, "decision", text=" ".join(actions))
            if plan.get("key_moment"):
                event(server, "key_moment", description=str(plan["key_moment"])[:200], category="milestone")
            state_after = None
            steps = []
            start = end = pose_of(state)
            tail_parts = []
            try:
                acted = True
                response = requests.post(f"{server}/action/traced", json={"actions": actions}, timeout=120)
                response.raise_for_status()
                result_body = response.json()
                result = f"executed {result_body.get('actions_executed')}"
                state_after = result_body.get("state_after")
                steps = result_body.get("steps") or []
                if steps:
                    start = steps[0].get("before") or start
                    end = next((st["after"] for st in reversed(steps) if st.get("after")), start)  # error steps have no pose
                if start.get("loaded", True) is False and end.get("loaded", True):
                    tail_parts.append(f" MAP LOADED {end.get('map_name')}")  # intro over, first real map
                elif start.get("loaded", True) is False:
                    pass  # still on the title/intro: no place to compare
                elif start.get("map_id") != end.get("map_id"):
                    tail_parts.append(f" MAP CHANGED {start.get('map_name')} -> {end.get('map_name')}")
                elif start.get("pos") == end.get("pos"):
                    ui_turn = bool(steps) and all(st.get("before", {}).get("ui") for st in steps if st.get("before"))
                    moved = any(p.get("map_id") != start.get("map_id") or p.get("pos") != start.get("pos")
                                for st in steps for p in (st.get("before"), st.get("after")) if p)
                    tail_parts.append(" (back at the starting position)" if moved else
                                      " (menu/dialog input, position unchanged)" if ui_turn else " (no movement)")
                blocked = {}
                for st in steps:
                    b, af = st.get("before"), st.get("after")
                    if b and (b.get("ui") or (af and af.get("ui"))):
                        continue  # cursor move inside a menu/dialog/battle
                    if st.get("action", "").startswith("walk_") and b and af and b.get("map_id") == af.get("map_id") and b.get("pos") == af.get("pos"):
                        blocked[st["action"]] = blocked.get(st["action"], 0) + 1
                if blocked:
                    tail_parts.append(" blocked walks: " + ", ".join(f"{k} x{v}" for k, v in blocked.items()))
                pages = []  # dialogue the batch skipped past — SYSTEM promises it is quoted back here
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
            except Exception as exc:
                result = f"action error: {exc}"
                tail_parts.append(f" action error: {exc}")
            if plan.get("notes"):
                notes = str(plan["notes"])[:600]
                with open(notes_path, "w") as output:
                    output.write(notes)
            history.append(f"turn {turn}: {fmt_pose(start)} did [{' '.join(actions)}] -> {fmt_pose(end)}{''.join(tail_parts)}")
            history_turns.append(turn)
            with open(log_path, "a") as output:
                output.write(json.dumps({
                    "turn": turn, "state": compact(state), "thinking": thinking,
                    "plan": plan, "result": result, "model_s": elapsed, "tokens": tokens,
                    # what the model was shown + what came back, so a run can be audited after the fact
                    "screen_text": screen_text, "map": amap, "feedback": history[-1], "steps": steps,
                    **observation,
                    "state_after": compact(state_after) if isinstance(state_after, dict) else None,
                }) + "\n")
            turns_done = turn
            # A milestone map can be entered and left inside one 6-action batch; the per-step RAM
            # poses expose those transient map_ids the pre/post-turn states miss (map rungs only —
            # party/flags/badge rungs still resolve on the full state_after below).
            for step in steps:
                after = step.get("after") if isinstance(step, dict) else None
                if isinstance(after, dict) and after.get("map_id") is not None:
                    record_milestones(server, tracker, {"map": {"map_id": after["map_id"]}}, turn)
            # A white-out halves the money (floor) and warps to the last Pokémon Center: no purchase does both.
            if isinstance(state_after, dict):
                money_before = (state.get("player") or {}).get("money")
                money_after = (state_after.get("player") or {}).get("money")
                if (isinstance(money_before, int) and isinstance(money_after, int) and money_before > 0
                        and money_after == money_before // 2
                        and (state.get("map") or {}).get("map_id") != (state_after.get("map") or {}).get("map_id")):
                    blackouts.append(turn)
                    print(f"💀 BLACKOUT (turn {turn})", flush=True)
            # /action supplies RAM state: credit even a milestone on the last budgeted turn.
            if isinstance(state_after, dict) and record_milestones(server, tracker, state_after, turn):
                print(f"🏆 Brock defeated at turn {turn} — ceiling reached, ending run.", flush=True)
                termination = "beat_brock"
                break
            if turn % 25 == 0:
                save_name = save_game(server, f"{run_id}-auto") or save_name
    except KeyboardInterrupt:
        termination = "interrupted"
        raise
    finally:
        if acted:
            save_name = save_game(server, f"{run_id}-auto") or save_name
        summary_path = write_summary(
            artifact_dir, run_id, model, provider, run_name, tracker, turns_done, budget,
            total_tokens, time.time() - run_start, notes, save_name,
            harness_git_sha, harness_files_sha, blackouts, termination, failed_attempts,
        )
    return summary_path


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model-key", required=True, help="exact key from models.yaml")
    parser.add_argument("--server", default="http://localhost:8765")
    parser.add_argument("--turns", type=int, default=1000)
    parser.add_argument("--run-name", default="")
    parser.add_argument("--no-frames", action="store_true", help="don't save frame PNGs")
    args = parser.parse_args(argv)
    if args.turns <= 0:
        parser.error("--turns must be positive")
    try:
        model = load_model(args.model_key)
        provider = make_provider(model)
    except (OSError, ValueError, yaml.YAMLError) as exc:
        parser.error(str(exc))
    try:
        run(model, provider, args.server, args.turns, args.run_name or args.model_key, no_frames=args.no_frames)
    except KeyboardInterrupt:
        print("Run interrupted; partial summary written.", flush=True)
        return 130
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
