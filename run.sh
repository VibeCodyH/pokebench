#!/usr/bin/env bash
# Usage: ./run.sh <models.yaml key>
# Optional: PYTHON=/path/to/python POKEMON_ROM=/path/to/Pokemon\ Red.gb
set -eu

if [ "$#" -ne 1 ]; then
    printf 'Usage: %s <model-key>\n' "$0" >&2
    exit 2
fi

cd -- "$(dirname -- "$0")"
root=$(pwd -P)
if [ -z "${PYTHON:-}" ]; then
    if [ -x "$root/.venv/bin/python" ]; then
        PYTHON="$root/.venv/bin/python"
    else
        PYTHON=python3
    fi
fi
export PYTHONDONTWRITEBYTECODE=1
model_key=$1
server=http://localhost:8765

# Validate the key, dependencies, credentials, and rates before resetting a game.
# Provider construction is offline; no model request is made here.
"$PYTHON" -c 'import sys; from run_benchmark import load_model, make_provider; make_provider(load_model(sys.argv[1]))' "$model_key"

mkdir -p "$root/logs"
stamp=$(date -u +%Y%m%d_%H%M%S)
run_name="$model_key-$stamp-$$"
run_log=$(mktemp "$root/logs/benchmark-$stamp-XXXXXX.log")

if ! curl --fail --silent --show-error --max-time 2 "$server/health" >/dev/null 2>&1; then
    rom=${POKEMON_ROM:-"$root/roms/Pokemon Red.gb"}
    if [ ! -f "$rom" ]; then
        printf 'ROM not found: %s (set POKEMON_ROM)\n' "$rom" >&2
        exit 1
    fi
    server_log=$(mktemp "$root/logs/server-$stamp-XXXXXX.log")
    SDL_VIDEODRIVER=dummy SDL_AUDIODRIVER=dummy nohup "$PYTHON" -u "$root/serve_live.py" \
        --rom "$rom" --port 8765 >"$server_log" 2>&1 </dev/null &
    server_pid=$!
    printf '%s\n' "$server_pid" >"$server_log.pid"
    printf 'Server log: %s\n' "$server_log"
fi

# A listening socket is not enough: wait for the emulator to finish booting.
attempt=0
until curl --fail --silent --show-error --max-time 2 "$server/health" 2>/dev/null |
    "$PYTHON" -c 'import json,sys; s=json.load(sys.stdin); sys.exit(0 if s.get("status") == "ok" and s.get("emulator_ready") else 1)' 2>/dev/null; do
    attempt=$((attempt + 1))
    if [ "$attempt" -ge 30 ]; then
        printf 'Server not ready at %s; inspect logs/ for startup errors.\n' "$server" >&2
        exit 1
    fi
    sleep 1
done

payload=$("$PYTHON" -c 'import json,sys; print(json.dumps({"name": sys.argv[1]}))' "$run_name")
curl --fail --silent --show-error --max-time 120 -H 'Content-Type: application/json' \
    --data "$payload" "$server/games/new" >/dev/null
curl --fail --silent --show-error --max-time 10 -H 'Content-Type: application/json' \
    --data '{"state":"running"}' "$server/control" >/dev/null

nohup "$PYTHON" -u "$root/run_benchmark.py" --model-key "$model_key" \
    --server "$server" --run-name "$run_name" >"$run_log" 2>&1 </dev/null &
runner_pid=$!
printf '%s\n' "$runner_pid" >"$run_log.pid"
printf 'Runner PID: %s\nRun name: %s\nRunner log: %s\nStream: %s/stream\n' \
    "$runner_pid" "$run_name" "$run_log" "$server"
