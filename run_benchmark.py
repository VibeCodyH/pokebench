#!/usr/bin/env python3
"""Run a models.yaml entry through the shared Pokémon Red benchmark harness.

    .venv/bin/python run_benchmark.py --model-key 'qwen3.8:27b'

Imports make no requests. The game must already exist and /control must be running
(run.sh handles that). Notes and artifacts start fresh for each invocation.
"""

import argparse
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
    SYSTEM,
    TEMPERATURE,
    build_map,
    compact,
    event,
    screenshot_b64,
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
                  harness_git_sha=None, harness_files_sha=None):
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
        "turns_used": turns_used,
        "wall_time_s": round(wall_s, 1),
        "tokens_in": tokens["prompt"],
        "tokens_out": tokens["completion"],
        "cost_usd": provider.cost(tokens),
        "youtube_url": None,
        "timestamp": time.strftime("%Y%m%d_%H%M%S"),
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
# A 480x432 PNG costs well under 1600 tokens on every provider we run; 8192 covers the
# largest output allowance.
_IMAGE_TOKENS = 1600
_OUTPUT_TOKENS = 8192
_SAFETY_TOKENS = 1024


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


def run(model, provider, server, budget=1000, run_name="run"):
    server = server.rstrip("/")
    os.makedirs(RUNS_DIR, exist_ok=True)
    slug = re.sub(r"[^A-Za-z0-9_-]+", "-", model["key"]).strip("-")[:80] or "model"
    prefix = f"{slug}-{time.strftime('%Y%m%d_%H%M%S')}-"
    artifact_dir = tempfile.mkdtemp(prefix=prefix, dir=RUNS_DIR)
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
            "model": model["api_model_id"], "think": model["think"], "ctx": model["num_ctx"],
            "route": ("local" if model["provider"] == "ollama" else "api"),
            "prompt_version": PROMPT_VERSION,
        }, timeout=10)
    except Exception:
        pass
    total_tokens = {"prompt": 0, "completion": 0}
    notes = ""
    history = []
    last_pos, same_pos = None, 0
    turn = 0
    save_name = None
    acted = False
    try:
        # Keep qwen_red's polling, retry delays, and attempt-based turn accounting.
        for turn in range(1, budget + 1):
            try:
                control = requests.get(f"{server}/control", timeout=10).json().get("state", "running")
            except Exception:
                control = "running"
            if control == "paused":
                time.sleep(3)
                continue
            if control == "stopped":
                print("control = stopped, exiting", flush=True)
                break

            try:
                response = requests.get(f"{server}/state", timeout=15)
                response.raise_for_status()
                state = response.json()
                response = requests.get(f"{server}/map/ascii", timeout=15)
                response.raise_for_status()
                amap = build_map(state) or response.text
                img = screenshot_b64(server)
            except Exception as exc:
                print(f"[turn {turn}] server not reachable ({exc}); retrying", flush=True)
                time.sleep(5)
                continue

            pos = ((state.get("map") or {}).get("map_id"),
                   json.dumps((state.get("player") or {}).get("position")))
            same_pos = same_pos + 1 if pos == last_pos else 0
            last_pos = pos
            if record_milestones(server, tracker, state, turn):
                print(f"🏆 Brock defeated at turn {turn} — ceiling reached, ending run.", flush=True)
                break
            stuck = (f"\nWARNING: position unchanged for {same_pos} turns. Do something different."
                     if same_pos >= 3 else "")
            head = f"NOTES:\n{notes or '(no notes yet)'}\n\nRECENT TURNS:\n"
            tail = (f"\n\nSTATE:\n{compact(state)}\n\nWALKABILITY MAP (you are @ at E5):\n"
                    f"{amap}{stuck}\n\nThe screenshot is attached. Take your turn.")
            recent = fit_recent(history, model["num_ctx"], len(SYSTEM) + len(head) + len(tail))
            user = head + "\n".join(recent) + tail
            started = time.time()
            try:
                plan, thinking, tokens = provider.chat(SYSTEM, user, img, SCHEMA, model["think"])
            except Exception as exc:
                print(f"[turn {turn}] model error: {exc}", flush=True)
                time.sleep(5)
                continue
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
            try:
                acted = True
                response = requests.post(f"{server}/action", json={"actions": actions}, timeout=120)
                response.raise_for_status()
                result_body = response.json()
                result = f"executed {result_body.get('actions_executed')}"
                state_after = result_body.get("state_after")
                steps = result_body.get("steps") or []
            except Exception as exc:
                result = f"action error: {exc}"
            if plan.get("notes"):
                notes = str(plan["notes"])[:600]
                with open(notes_path, "w") as output:
                    output.write(notes)
            mp = (state.get("map") or {}).get("map_name")
            pp = (state.get("player") or {}).get("position")
            history.append(f"turn {turn}: at {mp} {pp} did [{' '.join(actions)}] -> {result}")
            with open(log_path, "a") as output:
                output.write(json.dumps({
                    "turn": turn, "state": compact(state), "thinking": thinking,
                    "plan": plan, "result": result, "model_s": elapsed, "tokens": tokens,
                }) + "\n")
            # A milestone map can be entered and left inside one 6-action batch; the per-step RAM
            # poses expose those transient map_ids the pre/post-turn states miss (map rungs only —
            # party/flags/badge rungs still resolve on the full state_after below).
            for step in steps:
                after = step.get("after") if isinstance(step, dict) else None
                if isinstance(after, dict) and after.get("map_id") is not None:
                    record_milestones(server, tracker, {"map": {"map_id": after["map_id"]}}, turn)
            # /action supplies RAM state: credit even a milestone on the last budgeted turn.
            if isinstance(state_after, dict) and record_milestones(server, tracker, state_after, turn):
                print(f"🏆 Brock defeated at turn {turn} — ceiling reached, ending run.", flush=True)
                break
            if turn % 25 == 0:
                save_name = save_game(server, f"{run_id}-auto") or save_name
    finally:
        if acted:
            save_name = save_game(server, f"{run_id}-auto") or save_name
        summary_path = write_summary(
            artifact_dir, run_id, model, provider, run_name, tracker, turn, budget,
            total_tokens, time.time() - run_start, notes, save_name,
            harness_git_sha, harness_files_sha,
        )
    return summary_path


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model-key", required=True, help="exact key from models.yaml")
    parser.add_argument("--server", default="http://localhost:8765")
    parser.add_argument("--turns", type=int, default=1000)
    parser.add_argument("--run-name", default="")
    args = parser.parse_args(argv)
    if args.turns <= 0:
        parser.error("--turns must be positive")
    try:
        model = load_model(args.model_key)
        provider = make_provider(model)
    except (OSError, ValueError, yaml.YAMLError) as exc:
        parser.error(str(exc))
    try:
        run(model, provider, args.server, args.turns, args.run_name or args.model_key)
    except KeyboardInterrupt:
        print("Run interrupted; partial summary written.", flush=True)
        return 130
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
