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
from fastapi import HTTPException
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


_A_UNTIL_CAP = 40          # presses; 15 capped out on Oak's speeches (measured 2026-09-08)
_REOPEN_GRACE_TICKS = 6    # x30 frames = ~3 s of "is the next box coming?" after a close
_TILEMAP_ROW12 = 0xC3A0 + 12 * 20   # wTileMap row 12 = top edge of the standard text box
_BOX_CORNER = 0x79                  # top-left border tile; measured 0x79 open / overworld tile closed


def _transition_busy() -> bool:
    """wd730 bit 5: joypad ignored. Set during warps (fade + auto-step), scripted walks (Oak's
    intercept) and text printing; CLEAR while a text box or menu waits for input (measured
    2026-09-08). So it means 'the game is moving on its own right now'."""
    return bool(S._emulator.read_u8(_red.ADDR_JOY_IGNORE) & 0x20)


def _ui_open() -> bool:
    """A text box, menu or battle is on screen: direction presses move a cursor, not the player."""
    return _dialog_open() or _menu_open() or S._emulator.read_u8(_red.ADDR_BATTLE_TYPE) != 0


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


def _menu_open() -> bool:
    # Gen 1 overworld tileset tile IDs are < 0x60; 0x79 in the upper screen is the top-left corner of a menu
    # box (Yes/No prompt, shop list, Start menu at col 10 row 0, naming preset box at row 4), so the helper stops
    # instead of confirming the highlighted choice. Verified on a live boot 2026-09-08: the intro name-select
    # list stopped the helper with 0 presses (stop_reason menu). Yes/No boxes use the same border tile (inferred).
    if S._emulator.read_u8(_red.ADDR_BATTLE_TYPE) != 0:
        return False
    raw = S._emulator.read_range(0xC3A0, 12 * 20)  # wTileMap rows 0-11
    return _BOX_CORNER in raw


_TILEMAP = 0xC3A0
_TEXT_ROWS = (14, 16)  # the two text lines of the standard box
_red.GEN1_ENCODING.setdefault(0xBA, "é")  # POKéMON; upstream table lacks it
for _b, _ch in {0xBB: "'d", 0xBC: "'l", 0xBD: "'s", 0xBE: "'t", 0xBF: "'v", 0xE4: "'r", 0xE5: "'m",
                0xEF: "♂", 0xF5: "♀", 0xF2: ".", 0x9A: "(", 0x9B: ")", 0x9C: ":", 0x9D: ";", 0x9E: "[", 0x9F: "]"}.items():
    _red.GEN1_ENCODING.setdefault(_b, _ch)  # Gen 1 ligatures/punctuation; test run 3 T74 lost "OAK's" -> "OAK"


def _squash(lines):
    """Text prints letter by letter and scrolls up a line at a time, so samples every 30 frames
    are prefixes of each other. Keep the longest version of each line."""
    out = []
    for t in lines:
        if not t:
            continue
        if out and t.startswith(out[-1]):
            out[-1] = t
        elif out and out[-1].startswith(t):
            continue
        else:
            out.append(t)
    return out


_NUM_WARPS = 0xD3AE   # wNumberOfWarps; entries follow at wWarpEntries, 4 bytes each: y, x, dest warp id, dest map


def _warps() -> list:
    """[x, y] of every door/stairs/warp tile on the current map, from the game's own warp table.
    Test run 4 (2026-09-08): Red's front door rendered `.` on the grid while the prompt said doors
    read as `#`; she walked 'north toward the lab' into her own house 25 times."""
    n = S._emulator.read_u8(_NUM_WARPS)
    if not 0 < n <= 32:
        return []
    raw = S._emulator.read_range(_NUM_WARPS + 1, n * 4)
    return [[raw[i * 4 + 1], raw[i * 4]] for i in range(n)]


def _screen_text() -> str:
    """Every word on screen right now, decoded from wTileMap with the game's own charmap
    (letters are >= 0x80; overworld tiles are < 0x60 so they decode to nothing). This is
    what the model would read from the screenshot, as text: dialog, menus, battle HUD."""
    raw = S._emulator.read_range(_TILEMAP, 18 * 20)
    rows = []
    for r in range(18):
        line = "".join(_red.GEN1_ENCODING.get(b, "") for b in raw[r * 20:(r + 1) * 20])
        line = " ".join(line.split())
        if line:
            rows.append(line)
    return " / ".join(rows)


def _box_lines() -> str:
    raw = S._emulator.read_range(_TILEMAP, 18 * 20)
    out = []
    for r in _TEXT_ROWS:
        line = "".join(_red.GEN1_ENCODING.get(b, "") for b in raw[r * 20 + 1:r * 20 + 19])
        line = " ".join(line.split())
        if line:
            out.append(line)
    return " ".join(out)


async def _a_until_dialog_end() -> dict:
    """Press A until the text box is gone (max 15) — returns {presses, stop_reason}.
    History: upstream checked nonexistent 'dialog_active'; v2 screenshot-signature loop stopped on first
    REVISITED layout -> always one press late next to sign/NPC (7-turn loop in Viridian 2026-09-08). v3 reads
    wTileMap corner 0x79 from RAM, pre-checks no_box/menu and stops on menu to avoid confirming a choice."""
    if not _dialog_open():
        return {"presses": 0, "stop_reason": "no_box"}
    if _menu_open():
        return {"presses": 0, "stop_reason": "menu"}
    presses = 0
    stop_reason = "capped"
    said = [_box_lines()]  # transcript of what she skipped, so the words reach her turn history
    for _ in range(_A_UNTIL_CAP):
        await S._run_sync(S._emulator.press, "a", 8)  # 8-frame hold = reliable register
        await S._run_sync(S._emulator.tick, 30)
        presses += 1
        if _dialog_open():
            line = _box_lines()
            if line and line != said[-1]:
                said.append(line)
        if not _dialog_open():
            # Scripted scenes (intro, Oak's Lab) close the box, move sprites, then open the next
            # box on their own. Measured 2026-09-08: the helper returned "closed" after 1-2 presses
            # four turns in a row in the lab. Wait a moment without pressing; only a box that stays
            # closed is really the end.
            for _ in range(_REOPEN_GRACE_TICKS):
                await S._run_sync(S._emulator.tick, 30)
                if _dialog_open():
                    break
            else:
                stop_reason = "closed"
                break
        elif _menu_open():
            stop_reason = "menu"
            break
    return {"presses": presses, "stop_reason": stop_reason, "text": _squash(said)[:30]}


_SETTLE_OPEN_TICKS = 10  # 10 x 6 frames = 1 s for a box to appear after a press before we give up
_SETTLE_CAP_TICKS = 40   # 40 x 6 frames = 4 s max for the text to finish printing


async def _settle_text() -> None:
    """After a button press, let the game finish drawing before anyone reads the screen.
    Measured 2026-09-08 from a save state next to Oak's aide: press_a -> the frame captured right
    after shows NO box; the line prints over the next 1-3 s of real time. The harness read the
    empty frame, the model pressed A again and dismissed a line it never saw (12-turn loop in the
    lab). Upstream's dialog.active stays False with a full box on screen, so we watch the tiles:
    done when the box text has not changed for 30 frames, or no box showed up within 1 s."""
    stable, last = 0, None
    for i in range(_SETTLE_CAP_TICKS):
        await S._run_sync(S._emulator.tick, 6)
        if not _dialog_open():
            if i >= _SETTLE_OPEN_TICKS:
                return
            continue
        line = _box_lines()
        stable = stable + 1 if (line and line == last) else 0
        if stable >= 5:
            return
        last = line


_WARP_CAP_TICKS = 30  # 30 x 6 frames = 3 s for a door/stairs fade to finish
_FRAME_SETTLE_TICKS = 80  # 80 x 6 frames = 8 s for a scripted scene to hand control back before /frame


async def _settle_warp(stale: dict) -> dict:
    """Door and stairs warps flip the map id first; the player's coordinates only update when the
    fade ends, then leaving a building auto-walks one step off the door. Measured 2026-09-08
    (Oak's Lab): the pose read right after the walk said "Pallet Town (5,11)" (lab door tile) and
    /frame agreed until ~2 s later when it became (12,12); entering read "Oak's Lab (12,11)".
    Every warp in test run 3 logged such a line into her history. wd730 bit 5 (joypad ignored) is
    set for the fade + auto-step, but only ~0.1-0.2 s after the walk returns, so wait for BOTH the
    coordinates to leave the stale value and the bit to be clear; cap 3 s."""
    pose = stale
    for _ in range(_WARP_CAP_TICKS):
        await S._run_sync(S._emulator.tick, 6)
        pose = await S._run_sync(_pose)
        busy = await S._run_sync(lambda: S._emulator.read_u8(_red.ADDR_JOY_IGNORE) & 0x20)
        if pose.get("pos") != stale.get("pos") and not busy:
            await S._run_sync(S._emulator.tick, 6)
            return await S._run_sync(_pose)
    return pose


async def _execute_unlocked(action_str: str):
    a = action_str.strip().lower()
    if a == "a_until_dialog_end":
        return await _a_until_dialog_end()
    res = await _orig_execute(action_str)
    if a.startswith(("press_", "hold_")):
        await _settle_text()
    return res


async def _locked_execute(action_str: str):
    async with _lock:
        return await _execute_unlocked(action_str)


S._execute_action = _locked_execute


def _pose() -> dict:
    """Sync helper for /action/traced — run via S._run_sync."""
    mi = S._reader.read_map_info()  # {"map_id","map_name"}
    pl = S._reader.read_player()  # {"position":{"y","x"}, "facing", ...}
    pos = pl.get("position") or {}
    return {"map_id": mi.get("map_id"), "map_name": mi.get("map_name"), "pos": [pos.get("x"), pos.get("y")], "facing": pl.get("facing"),
            "ui": _ui_open()}


@S.app.middleware("http")
async def _busy_guard(request, call_next):
    global _busy
    mutating = request.method == "POST" and request.url.path.split("/")[1] in ("save", "load", "games")
    if mutating:
        _busy += 1
        if request.url.path == "/games/new":
            _milestones.clear(); _run_meta.clear()
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


@S.app.post("/action/traced")
async def traced_action(req: S.ActionRequest):
    """Like upstream /action but records per-action before/after and a_until result."""
    S._ensure_emulator()
    steps = []
    executed = 0
    try:
        for a in req.actions:
            async with _lock:  # one lock span per action: the idle ticker cannot move the game between the pose reads
                before = await S._run_sync(_pose)
                try:
                    detail = await _execute_unlocked(a)
                except ValueError as e:
                    steps.append({"action": a, "error": str(e)})
                    break
                after = await S._run_sync(_pose)
                if after.get("map_id") != before.get("map_id"):
                    after = await _settle_warp(after)
                said = await S._run_sync(lambda: _box_lines() if _dialog_open() else "")
            step = {"action": a, "before": before, "after": after, "dialog": detail}
            if said and not isinstance(detail, dict):
                step["said"] = said  # the page a plain press left on screen (a_until carries its own transcript)
            steps.append(step)
            executed += 1
        state_after = await S._run_sync(S._get_state_dict)
        if S._active_session is not None and S._session_mgr is not None:
            s = S._active_session.stats
            s["actions"] = s.get("actions", 0) + executed
            s["turns"] = s.get("turns", 0) + 1
            S._session_mgr.save(S._active_session)
        try:
            png_bytes = await S._run_sync(S._get_screenshot_bytes)
            screenshot_b64 = base64.b64encode(png_bytes).decode("ascii")
        except Exception:
            screenshot_b64 = None
        await S.broadcast({
            "type": "action",
            "actions": req.actions,
            "actions_executed": executed,
            "state_after": state_after,
        })
        if screenshot_b64:
            await S.broadcast({
                "type": "screenshot",
                "data": {"image": screenshot_b64, "format": "png"},
            })
        return {"success": True, "actions_executed": executed, "steps": steps, "state_after": state_after}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Action error: {e}")


from milestones import MILESTONES as _LADDER  # noqa: E402  (same dir; baked into the image with us)

_milestones: dict = {}  # key -> turn, for the current game; cleared on /games/new


@S.app.post("/milestones")
async def post_milestone(body: dict):
    """Harness reports a newly hit milestone {key, label, turn}; stored for /stream refreshes and broadcast live."""
    key, turn = body.get("key"), body.get("turn")
    if key and key not in _milestones:
        _milestones[key] = turn
        await S.broadcast({"type": "milestone", "key": key, "label": body.get("label"), "turn": turn})
    return {"success": True, "hit": _milestones}


_run_meta: dict = {}  # {model, think, ctx, route, prompt_version} from the harness; cleared on /games/new


@S.app.post("/run_meta")
async def post_run_meta(body: dict):
    _run_meta.clear(); _run_meta.update({k: v for k, v in body.items() if isinstance(v, (str, int, float))})
    await S.broadcast({"type": "run_meta", **_run_meta})
    return {"success": True}


@S.app.get("/run_meta")
async def get_run_meta():
    return _run_meta


@S.app.get("/milestones")
async def get_milestones():
    return {"ladder": [{"key": k, "label": l} for k, l, _ in _LADDER], "hit": _milestones}


@S.app.get("/frame")
async def get_frame():
    """One consistent frame for the harness: state + screenshot + ascii."""
    S._ensure_emulator()
    async with _lock:
        # Test run 3 (2026-09-08): black or fading screenshots and pre-warp coordinates went to the model
        # (T121/T186/T189), and Oak's intercept ran while she was thinking so the prompt said Pallet but the
        # actions started in the lab (T74->T75). Wait for the game to hand control back, cap 8 s.
        for _ in range(_FRAME_SETTLE_TICKS):
            if not await S._run_sync(_transition_busy):
                break
            await S._run_sync(S._emulator.tick, 6)

        def _build():
            state = S._get_state_dict()
            png = S._get_screenshot_bytes()
            b64 = base64.b64encode(png).decode("ascii")
            ascii_text = (state.get("collision") or {}).get("ascii")
            return {"state": state, "screenshot_b64": b64, "ascii": ascii_text, "screen_text": _screen_text(), "warps": _warps()}
        data = await S._run_sync(_build)
    return data


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
