#!/usr/bin/env python3
"""pokemon-agent server + a live idle ticker.

Upstream only advances the emulator while an /action runs, so the dashboard shows one frame per turn.
This wrapper keeps the Game Boy running at real time between actions (6 frames per 100 ms) and pushes a
screenshot to the dashboard WebSocket ~10x/s. An asyncio lock serialises the ticker with /action, and a
middleware pauses the ticker while any state-mutating POST (save/load/games) is in flight.

  serve_live.py --rom "roms/Pokemon Red.gb" [--port 8765] [--load-state zelda-auto]
"""
import argparse
import asyncio
import base64
import os
import time

import uvicorn
from pokemon_agent import server as S
from pokemon_agent.memory import red as _red

# --- Fix: read the ACTIVE enemy battle mon, not the stale enemy-party struct. ---
# Upstream read_battle reads the enemy PARTY (0xD89D/0xD8A4), which in a WILD battle
# still holds the last trainer's team (e.g. the rival's Squirtle), so every wild
# encounter is mislabeled. The active battle mon lives at wEnemyMon (0xCFE5).
# Verified on a live save-state: 0xD89D=177 (Squirtle, stale) vs 0xCFE5=36 (Pidgey).
_ENEMY_MON = 0xCFE5  # species+0, HP+1, status+4, moves+8, level+0x0E, maxHP+0x0F

def _read_battle_active(self):
    bt = self.emu.read_u8(_red.ADDR_BATTLE_TYPE)
    result = {"in_battle": bt != 0,
              "type": {0: "none", 1: "wild", 2: "trainer"}.get(bt, f"unknown({bt})")}
    if bt != 0:
        m = self.emu.read_range(_ENEMY_MON, 0x20)
        sid = m[0]
        result["enemy"] = {
            "species_id": sid,
            "dex_number": _red.INTERNAL_TO_DEX.get(sid, 0),
            "species": _red.species_name_from_index(sid),
            "level": m[0x0E],
            "hp": (m[1] << 8) | m[2],
            "max_hp": (m[0x0F] << 8) | m[0x10],
            "status": self._decode_status(m[4]),
            "moves": [_red.MOVE_NAMES.get(m[8 + j], f"???({m[8 + j]})")
                      for j in range(4) if m[8 + j]],
        }
    return result

_red.RedBlueMemoryReader.read_battle = _read_battle_active

FRAMES_PER_TICK = 2          # 2 frames per 33 ms loop = real time
TICK_PERIOD = 1 / 30

_lock = asyncio.Lock()
_busy = 0
_orig_execute = S._execute_action


_TILEMAP_ROW12 = 0xC3A0 + 12 * 20   # wTileMap row 12 = top edge of the standard text box
_BOX_CORNER = 0x79                  # top-left border tile; measured 0x79 open / overworld tile closed


def _dialog_open() -> bool:
    """Positive dialog check from RAM. The standard text box is drawn at (0,12) with
    corner tile 0x79; it is gone the frame the box closes. In battle the box is
    permanent, so there we treat a nested menu corner (FIGHT/move box) in row 12
    as 'text finished'."""
    row = S._emulator.read_range(_TILEMAP_ROW12, 20)
    if row[0] != _BOX_CORNER:
        return False
    if S._emulator.read_u8(_red.ADDR_BATTLE_TYPE) != 0 and _BOX_CORNER in row[1:]:
        return False
    return True


async def _a_until_dialog_end() -> None:
    """Press A until the text box is gone (max 15). Upstream checked a nonexistent
    'dialog_active' key. Our v2 screenshot-signature loop stopped on the first
    REVISITED layout, which next to a sign/NPC meant: close (new layout, keep
    going) -> A re-opens page 1 (seen, stop) = always one press late with the box
    open again; the model saw the box, called it again, and looped (7-turn loop
    observed in Viridian, 2026-09-08). Reading the box corner from wTileMap stops
    exactly on the close."""
    for _ in range(15):
        await S._run_sync(S._emulator.press, "a", 8)  # 8-frame hold = reliable register
        await S._run_sync(S._emulator.tick, 30)
        if not _dialog_open():
            break


async def _locked_execute(action_str: str) -> None:
    async with _lock:
        if action_str.strip().lower() == "a_until_dialog_end":
            return await _a_until_dialog_end()
        return await _orig_execute(action_str)


S._execute_action = _locked_execute


@S.app.middleware("http")
async def _busy_guard(request, call_next):
    global _busy
    mutating = request.method == "POST" and request.url.path.split("/")[1] in ("save", "load", "games")
    if mutating:
        _busy += 1
        async with _lock:  # wait for any in-flight tick, then hold nothing (handler runs unlocked)
            pass
    try:
        return await call_next(request)
    finally:
        if mutating:
            _busy -= 1


_wrapped_emu = None


def _wrap_tick(emu):
    """Make every emulator tick (idle ticker AND /action presses) stream frames at ~30 fps, paced to real time."""
    orig = emu.tick
    last_shot = [0.0]

    def tick(frames: int = 1) -> None:
        for _ in range(frames):
            t0 = time.time()
            orig(1)
            now = time.time()
            if S._ws_clients and S._loop is not None and now - last_shot[0] >= 1 / 30:
                last_shot[0] = now
                try:
                    png = S._get_screenshot_bytes()
                    asyncio.run_coroutine_threadsafe(S.broadcast({
                        "type": "screenshot",
                        "data": {"image": base64.b64encode(png).decode("ascii"), "format": "png"}}), S._loop)
                except Exception as e:
                    print(f"[stream] {e}")
            # pace to real time (1/60 s per frame) only while someone is watching
            if S._ws_clients:
                time.sleep(max(0.0, 1 / 60 - (time.time() - t0)))

    emu.tick = tick
    return emu


async def _ticker():
    global _wrapped_emu
    await asyncio.sleep(2)
    while True:
        t0 = time.time()
        emu = S._emulator
        if emu is not None and emu is not _wrapped_emu:
            _wrapped_emu = _wrap_tick(emu)
        if emu is not None and _busy == 0:
            async with _lock:
                try:
                    await S._run_sync(emu.tick, FRAMES_PER_TICK)
                except Exception as e:  # never let the ticker die
                    print(f"[ticker] {e}")
        await asyncio.sleep(max(0.0, TICK_PERIOD - (time.time() - t0)))


from fastapi.responses import FileResponse  # noqa: E402

_STREAM_HTML = os.path.join(os.path.dirname(os.path.abspath(__file__)), "stream.html")


@S.app.get("/stream")
async def stream_page():
    """Fixed-size OBS-friendly view: canvas fed by the WebSocket frames + Qwen's narration."""
    return FileResponse(_STREAM_HTML, media_type="text/html", headers={"Cache-Control": "no-store"})


@S.app.get("/events/recent")
async def recent_events(n: int = 20):
    """Polling fallback for the stream page: last n narration/milestone events."""
    return {"events": list(S._event_history)[-n:]}


@S.app.on_event("startup")
async def _start_ticker():
    asyncio.create_task(_ticker())


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--rom", required=True)
    ap.add_argument("--port", type=int, default=8765)
    ap.add_argument("--load-state", default=None)
    ap.add_argument("--data-dir", default="~/.pokemon-agent")
    a = ap.parse_args()
    S.configure(S.GameConfig(rom_path=os.path.abspath(a.rom), game_type="red", port=a.port,
                             data_dir=os.path.expanduser(a.data_dir), load_state=a.load_state))
    uvicorn.run(S.app, host="0.0.0.0", port=a.port, log_level="warning")


if __name__ == "__main__":
    main()
