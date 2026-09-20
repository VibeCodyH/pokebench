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
import threading
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
# wEnemyMon is only (re)loaded at the send-out, so during a trainer's "wants to fight!" intro it still holds
# the PREVIOUS battle's mon (Gemini run 2026-09-10: T469 showed a Route 2 Pidgey, T503 a half-dead Sandshrew,
# as the "current" opponent). pokered InitBattleCommon writes $ff to wEnemyMonPartyPos (struct offset 3) right
# before wIsInBattle := TRAINER_BATTLE, and LoadEnemyMonData overwrites it with the slot index at send-out.
_NOT_SENT_OUT = 0xFF

def _read_battle_active(self):
    bt = self.emu.read_u8(_red.ADDR_BATTLE_TYPE)
    result = {"in_battle": bt != 0,
              "type": {0: "none", 1: "wild", 2: "trainer"}.get(bt, f"unknown({bt})")}
    if bt == 0:
        return result
    m = self.emu.read_range(_ENEMY_MON, 0x20)
    if m[0] == 0 or (bt == 2 and m[3] == _NOT_SENT_OUT):
        result["enemy"] = None
        result["opponent"] = "not sent out yet"
    else:
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


_A_UNTIL_CAP = 100         # presses; 15 capped out on Oak's speeches (measured 2026-09-08); 40 capped on the Pokedex speech (test run 7, 18 boxes in 40 presses)
_REOPEN_GRACE_TICKS = 6    # x30 frames = ~3 s of "is the next box coming?" after a close
_TILEMAP_ROW12 = 0xC3A0 + 12 * 20   # wTileMap row 12 = top edge of the standard text box
_BOX_CORNER = 0x79                  # top-left border tile; measured 0x79 open / overworld tile closed
_MENU_CURSOR = 0xED                 # ▶ menu-selection cursor; present only while a menu awaits a choice (verified 2026-09-09)
# The level-up box shows these four labels with the "grew to level N!" text box still open.
# The STATUS page shows them too, but with no text box, so it stays a readable UI (see below).
_LEVEL_UP_STATS = frozenset({"ATTACK", "DEFENSE", "SPEED", "SPECIAL"})
# Both caps bound a press loop that would otherwise run the full _A_UNTIL_CAP at full speed.
_UNSETTLED_PRESS_CAP = 8   # presses allowed while the screen refuses to hold still
_DEX_PAGE_PRESS_CAP = 6    # presses allowed on a ShowPokedexData page (starter pick needs ~2)


def _dex_data_page(raw) -> bool:
    """The ShowPokedexData border WITHOUT the list's column-14 divider. That page asks nothing --
    only A advances it, two text pages then it closes into the Yes/No -- but _menu_open() reports
    it as a menu, so a_until used to break there with 0 presses (#32).

    The Start-menu Pokedex wears the same border and there A plays the cry instead of advancing,
    which is why this is capped rather than trusted: worst case is _DEX_PAGE_PRESS_CAP wasted
    presses inside ONE turn, against the several turns the 0-press break was costing."""
    head = bytes(raw[:20]) == b"\x63" + b"\x64" * 18 + b"\x65" and raw[20] == 0x66 and raw[39] == 0x67
    if not head:
        return False
    return not (raw[14] == 0x71 and bytes(raw[34:355:20]) == bytes([0x71, 0x70]) * 8 + b"\x71")


_BUSY_MASK = 0xA1   # 0xD730 bits 0 (scripted NPC movement) + 5 (joypad ignored) + 7 (simulated movement)
_BLANK_DISTINCT = 3  # a tilemap with <= this many distinct tile ids is a black/fade frame


def _transition_busy() -> bool:
    """0xD730 (wd730): bit 5 = joypad ignored, bit 7 = simulated/scripted movement, bit 0 = scripted
    NPC movement (Oak's escort). The mask is 0xA1 and deliberately EXCLUDES bit 6 (0x40, no-text-delay):
    v13 read the whole byte != 0 and treated the Charmander info screen (0x40 set) as busy, so every
    /frame there waited ~8 s (Codex run-9). Bit 0 was added after Codex run-10 caught T39/T49 escort
    frames leaking with only bit 0 set; measured 2026-09-09 that bit 0 is NEVER set during ambient
    overworld NPC movement (40 Pallet + 15 lab samples all 0), so it is safe in the mask.
    A near-blank tilemap (<= 3 distinct tile ids) is a fade/black/wipe frame, never a playable screen
    (T39/T59 black screenshot + all-# grid before the rival battle); normal screens have 10-38."""
    if S._emulator.read_u8(_red.ADDR_JOY_IGNORE) & _BUSY_MASK:
        return True
    raw = S._emulator.read_range(_TILEMAP, 18 * 20)
    return len(set(raw)) <= _BLANK_DISTINCT


def _ui_open() -> bool:
    """A text box, menu or battle is on screen: direction presses move a cursor, not the player."""
    return _dialog_open() or _menu_open() or S._emulator.read_u8(_red.ADDR_BATTLE_TYPE) != 0


def _dialog_open() -> bool:
    """Positive dialog check from RAM. The standard text box is drawn at (0,12) with
    corner tile 0x79. A menu may overlap the box; report both flags in that case."""
    return S._emulator.read_u8(_TILEMAP_ROW12) == _BOX_CORNER


def _menu_open() -> bool:
    raw = S._emulator.read_range(_TILEMAP, 18 * 20)
    # ShowPokedexData uses its own border tiles (also used for the starter preview).
    # Identify the layout, not a count of letter-range tiles that also matches the title.
    if bytes(raw[:20]) == b"\x63" + b"\x64" * 18 + b"\x65" and raw[20] == 0x66 and raw[39] == 0x67:
        return True
    # The Pokédex list has an alternating vertical divider in column 14.
    if raw[14] == 0x71 and bytes(raw[34:355:20]) == bytes([0x71, 0x70]) * 8 + b"\x71":
        return True
    # pokered draws these borders BEFORE polling input: upper-screen Yes/No, Mart,
    # PC, naming and Start menus; FIGHT at (8,12). Move selection also draws a
    # TYPE/PP box at (0,8). Do not depend on the cursor having appeared yet.
    for r in range(13):
        for c in range(19):
            if (r, c) == (12, 0):
                continue  # the standard dialogue box itself
            i = r * 20 + c
            if raw[i] == _BOX_CORNER and raw[i + 1] == 0x7A and raw[i + 20] == 0x7C:
                return True  # ┌─ with │ below; an isolated title/boot tile is not a box
    # Party selection uses a cursor above the standard box, including outside battle.
    return _MENU_CURSOR in raw and (_dialog_open() or S._emulator.read_u8(_red.ADDR_BATTLE_TYPE) != 0)


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
    """[x, y, dest_map] of every door/stairs/warp tile on the current map, from the game's own warp
    table. dest_map 0xFF = LAST_MAP (the outdoor map you came in from, i.e. this is the way out);
    anything else is another map (stairs to the other floor, a gate, a cave mouth).
    Test run 4 (2026-09-08): Red's front door rendered `.` on the grid while the prompt said doors
    read as `#`; she walked 'north toward the lab' into her own house 25 times.
    Test run 6 (2026-09-09): stairs and exit mat both rendered `D`; she rode the stairs 1F<->2F for
    15 turns thinking the stairs were the door out (measured: lab mat = 0xFF, house stairs = 0x26)."""
    n = S._emulator.read_u8(_NUM_WARPS)
    if not 0 < n <= 32:
        return []
    raw = S._emulator.read_range(_NUM_WARPS + 1, n * 4)
    return [[raw[i * 4 + 1], raw[i * 4], raw[i * 4 + 3]] for i in range(n)]


def _screen_text() -> str:
    """Every word on screen right now, decoded from wTileMap with the game's own charmap
    (letters are >= 0x80; overworld tiles are < 0x60 so they decode to nothing). This is
    what the model would read from the screenshot, as text: dialog, menus, battle HUD.
    Only decode when a box/menu is actually up: the title screen draws its logo with
    tile ids in the letter range, which otherwise decodes to a fake 'ABCDEFG...' alphabet the
    model reads as a name-entry screen (Codex run-10, T2)."""
    if not (_dialog_open() or _menu_open()):
        return ""
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
    """Advance dialogue with at most 100 single-frame A presses, stopping at a choice/menu.
    Check settled RAM before the first press and after every release; never hold A
    across the transition from a text page to a menu's input loop."""
    presses = 0
    unsettled_presses = 0   # presses spent while settle kept coming back "capped"
    dex_presses = 0         # presses spent on a ShowPokedexData page
    stop_reason = "capped"
    said, trace = [], []
    settle = await _settle_screen(_FRAME_SETTLE_TICKS)
    for _ in range(_A_UNTIL_CAP + 1):
        raw = bytes(S._emulator.read_range(_TILEMAP, 18 * 20))
        dialog_open, menu_open = _dialog_open(), _menu_open()
        on_dex_page = _dex_data_page(raw)
        in_battle = S._emulator.read_u8(_red.ADDR_BATTLE_TYPE) != 0
        if presses:
            trace.append({"press": presses, "ui": dialog_open or menu_open or in_battle,
                          "dialog_open": dialog_open, "menu_open": menu_open,
                          "in_battle": in_battle, "settle": settle, "screen_text": _screen_text()})
        if dialog_open:
            said.append(_box_lines())
        if menu_open:
            words = set(_screen_text().replace(" / ", " ").split())
            # The level-up box draws a border like a menu but asks nothing: pokered leaves the
            # "<NAME> grew to level N!" text box open behind it and only A dismisses it. Stopping
            # here returned 0 presses, so a model that kept calling this never left the screen --
            # run muse-glimmer-30b-20260912_204805 lost 118 turns across three such wedges.
            level_up = dialog_open and _LEVEL_UP_STATS <= words
            if not (level_up or (on_dex_page and dex_presses < _DEX_PAGE_PRESS_CAP)):
                stop_reason = "choice" if {"YES", "NO"} <= words else "menu"
                break
        # A page only A can clear is still a page only A can clear when the screen will not
        # hold still. _dialog_open reads the box corner out of RAM, so a true reading means the
        # box IS drawn -- the empty-frame race _settle_after guards against cannot be live here.
        # Astra sat on the Viridian Mart parcel clerk for three turns because this broke with 0
        # presses while a dialog box was open on screen (#45). Bounded, because the post-press
        # settle caps too and this would otherwise burn all 100 presses at full speed.
        may_press = dialog_open or on_dex_page
        if settle == "capped" and (not may_press or unsettled_presses >= _UNSETTLED_PRESS_CAP):
            break
        if not may_press:
            stop_reason = "closed"
            break
        if presses == _A_UNTIL_CAP:
            break
        await S._run_sync(S._emulator.press, "a", 1)
        presses += 1
        if on_dex_page:
            dex_presses += 1
        if settle == "capped":
            unsettled_presses += 1
        settle = await _settle_screen(_FRAME_SETTLE_TICKS, grace=True)
    return {"presses": presses, "stop_reason": stop_reason, "text": _squash(said),
            "trace": trace, "settle": settle}


_SETTLE_CAP_TICKS = 40   # 40 x 6 frames = 4 s max for the text to finish printing
_WARP_CAP_TICKS = 30  # 30 x 6 frames = 3 s for a door/stairs fade or scripted move to hand control back
_FRAME_SETTLE_TICKS = 80  # 80 x 6 frames = 8 s for a scripted scene to hand control back before /frame


_ARROW_TILES = (0xEE, 0xED)  # blinking "more text" arrow: normalize so a waiting box counts as stable


def _screen_sig() -> bytes:
    raw = bytes(S._emulator.read_range(_TILEMAP, 18 * 20))
    return raw.translate(bytes.maketrans(bytes(_ARROW_TILES), b"\x7f\x7f"))


async def _settle_screen(cap_ticks: int, grace: bool = False) -> str:
    """Wait for stable tilemap reads with scripted movement/fades clear, six frames apart.
    A plain overworld frame settles after 2 stable reads. Once a script/fade was seen in this wait
    (or the caller passes grace=True: the dialogue helper after a box closes), require the full
    reopening grace interval: scripts pause on an unchanged tilemap before drawing the next box
    (Oak's lab, turns 12->13 and 18->19 of the 2026-09-10 audit). Never press a button here."""
    same, last, saw_busy = 0, None, grace
    for _ in range(cap_ticks):
        await S._run_sync(S._emulator.tick, 6)
        sig = await S._run_sync(_screen_sig)
        busy = await S._run_sync(_transition_busy)
        saw_busy = saw_busy or busy
        same = same + 1 if sig == last and not busy else 0
        last = None if busy else sig
        stable_ticks = 2 if _dialog_open() or not saw_busy else _REOPEN_GRACE_TICKS * 30 // 6
        if same >= stable_ticks:
            return "cleared"
    return "capped"


_last_settle: dict = {}  # busy_reason of the most recent _settle_after, surfaced in /action/traced for review


async def _settle_after(action: str) -> None:
    """After any action: wait for scripted movement to hand control back (ledge jumps, Oak's
    intercept, door fades; cap 3 s), then for the screen to stop changing (cap 4 s). Measured
    2026-09-08: press_a next to Oak's aide returned before the box drew, so the frame the model
    got was empty and the next A dismissed a line she never read (12-turn loop).
    The busy flag must read CLEAR twice in a row before we call it settled: a single sample can
    land in the gap between one scripted step ending and the next beginning (Codex run-9 review,
    T35->T36: /frame caught Oak's escort mid-walk, reporting the lab door pose while the script
    was still walking her to the aide)."""
    clear = 0
    for i in range(_WARP_CAP_TICKS):
        if await S._run_sync(_transition_busy):
            clear = 0
        else:
            clear += 1
            if clear >= 2:
                break
        await S._run_sync(S._emulator.tick, 6)
    screen_settle = await _settle_screen(_SETTLE_CAP_TICKS)
    _last_settle["busy_reason"] = screen_settle  # a later clear can finish an initially capped script wait


async def _settle_warp(stale: dict) -> dict:
    """Door and stairs warps flip the map id first; the player's coordinates only update when the
    fade ends, then leaving a building auto-walks one step off the door. Measured 2026-09-08
    (Oak's Lab): the pose read right after the walk said "Pallet Town (5,11)" (lab door tile) and
    /frame agreed until ~2 s later when it became (12,12); entering read "Oak's Lab (12,11)".
    Every warp in test run 3 logged such a line into her history. The joypad-ignored bits are set
    for the fade + auto-step but only ~0.1-0.2 s after the walk returns, so wait for BOTH the
    coordinates to leave the stale value and the flag to be clear; cap 3 s."""
    pose = stale
    for _ in range(_WARP_CAP_TICKS):
        await S._run_sync(S._emulator.tick, 6)
        pose = await S._run_sync(_pose)
        busy = await S._run_sync(_transition_busy)
        if pose.get("pos") != stale.get("pos") and not busy:
            await S._run_sync(S._emulator.tick, 6)
            return await S._run_sync(_pose)
    return pose


async def _execute_unlocked(action_str: str):
    a = action_str.strip().lower()
    if a == "a_until_dialog_end":
        res = await _a_until_dialog_end()
        _last_settle["busy_reason"] = res["settle"]  # the helper already settled its final traced snapshot
        return res
    res = await _orig_execute(action_str)
    await _settle_after(a)
    return res


async def _locked_execute(action_str: str):
    async with _lock:
        return await _execute_unlocked(action_str)


S._execute_action = _locked_execute


_MAP_HEADER = 0xD368  # wCurMapHeight, wCurMapWidth: both 0 until the first overworld map is loaded


def _map_loaded() -> bool:
    """False on the title screen and through Oak's intro/naming: wCurMap/wYCoord/wXCoord already hold
    Red's House 2F (3,6) then (InitPlayerData), but no map header is loaded until the speech ends.
    Measured 2026-09-11 on a fresh boot: h/w stay 0 through the whole intro, become 4/4 one A press
    after wd732 bit 0 sets, and the player can move on the next press."""
    return S._emulator.read_range(_MAP_HEADER, 2) != b"\x00\x00"


def _state_dict() -> dict:
    """S._get_state_dict() with map.loaded stamped, so the harness never reports intro coordinates as a place."""
    state = S._get_state_dict()
    if isinstance(state.get("map"), dict):
        state["map"]["loaded"] = _map_loaded()
    return state


def _pose() -> dict:
    """Sync helper for /action/traced — run via S._run_sync."""
    mi = S._reader.read_map_info()  # {"map_id","map_name"}
    pl = S._reader.read_player()  # {"position":{"y","x"}, "facing", ...}
    pos = pl.get("position") or {}
    return {"map_id": mi.get("map_id"), "map_name": mi.get("map_name"), "pos": [pos.get("x"), pos.get("y")], "facing": pl.get("facing"),
            "ui": _ui_open(), "loaded": _map_loaded()}


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

# --- game audio: PyBoy fills a stereo sample buffer every frame (window="null" still emulates the APU).
# Every tick appends it to a small ring; /audio.pcm drains the ring at wall-clock rate so the recorder's
# FFmpeg gets a continuous PCM stream (silence-padded when the game idles, oldest dropped on overrun).
_AUDIO_RING_SECONDS = 0.5
_audio_lock = threading.Lock()
_audio_ring = bytearray()
_audio_info: dict = {}  # sample_rate / channels / sample_format / bytes_per_sample, filled on the first tick
_audio_stats = {"captured_bytes": 0, "held_bytes": 0, "dropped_bytes": 0}  # producer vs consumer health, see /audio/info


def _audio_capture(emu) -> None:
    try:
        snd = emu._pyboy.sound
        if not _audio_info:
            fmt = snd.raw_buffer_format
            _audio_info.update(sample_rate=snd.sample_rate, channels=2,
                               sample_format={"b": "s8", "h": "s16le"}[fmt], bytes_per_sample={"b": 1, "h": 2}[fmt])
        head = snd.raw_buffer_head
        if head <= 0:
            return
        chunk = bytes(snd.raw_buffer[:head])
    except Exception as e:
        print(f"[audio] {e}")
        return
    cap = int(_audio_info["sample_rate"] * _audio_info["channels"] * _audio_info["bytes_per_sample"] * _AUDIO_RING_SECONDS)
    with _audio_lock:
        _audio_ring.extend(chunk)
        _audio_stats["captured_bytes"] += len(chunk)
        if len(_audio_ring) > cap:
            _audio_stats["dropped_bytes"] += len(_audio_ring) - cap
            del _audio_ring[:len(_audio_ring) - cap]


def _wrap_tick(emu):
    """Make every emulator tick (idle ticker AND /action presses) stream frames at ~30 fps, paced to real time."""
    orig = emu.tick
    last_shot = [0.0]
    deadline = [0.0]  # absolute frame schedule: loop overhead is absorbed instead of accumulating (audio needs 60.00 fps)

    def tick(frames: int = 1) -> None:
        for _ in range(frames):
            orig(1)
            _audio_capture(emu)
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
                now = time.time()
                if deadline[0] < now - 0.5:  # first frame, or a stall (save/load, no viewers): resync, don't sprint
                    deadline[0] = now
                deadline[0] += 1 / 60
                if deadline[0] > now:
                    time.sleep(deadline[0] - now)

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


from fastapi.responses import FileResponse, StreamingResponse  # noqa: E402

_STREAM_HTML = os.path.join(os.path.dirname(os.path.abspath(__file__)), "stream.html")


@S.app.get("/stream")
async def stream_page():
    """Fixed-size OBS-friendly view: canvas fed by the WebSocket frames + Qwen's narration."""
    return FileResponse(_STREAM_HTML, media_type="text/html", headers={"Cache-Control": "no-store"})


@S.app.get("/audio/info")
async def audio_info():
    """Raw PCM parameters for /audio.pcm (503 until the emulator has ticked once)."""
    if not _audio_info:
        raise HTTPException(503, "no audio yet")
    return {**_audio_info, **_audio_stats, "ring_bytes": len(_audio_ring)}


@S.app.get("/audio.pcm")
async def audio_pcm():
    """Endless raw PCM of the game audio, paced to wall clock (feed FFmpeg with -f <sample_format> -ar -ac)."""
    if not _audio_info:
        raise HTTPException(503, "no audio yet")
    rate, frame_bytes = _audio_info["sample_rate"], _audio_info["channels"] * _audio_info["bytes_per_sample"]
    with _audio_lock:  # start fresh so the stream sits as close to the video as the ring allows
        _audio_ring.clear()

    async def gen():
        prefill = int(rate * 0.06) * frame_bytes  # ~60 ms head start absorbs producer jitter without underruns
        for _ in range(50):
            with _audio_lock:
                if len(_audio_ring) >= prefill:
                    break
            await asyncio.sleep(0.02)
        last = bytes(frame_bytes)  # on underrun repeat the last stereo frame: a hold, not a step down to zero (that clicks)
        start, sent = time.time(), 0
        while True:
            await asyncio.sleep(0.02)
            due = int((time.time() - start) * rate) - sent
            if due <= 0:
                continue
            need = due * frame_bytes
            with _audio_lock:
                take = bytes(_audio_ring[:need])
                del _audio_ring[:need]
            if take:
                last = take[-frame_bytes:]
            if len(take) < need:
                _audio_stats["held_bytes"] += need - len(take)
                take += last * ((need - len(take)) // frame_bytes)
            sent += due
            yield take

    return StreamingResponse(gen(), media_type="application/octet-stream", headers={"Cache-Control": "no-store"})


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
                _last_settle.pop("busy_reason", None)
                try:
                    detail = await _execute_unlocked(a)
                except ValueError as e:
                    steps.append({"action": a, "error": str(e)})
                    break
                settle = _last_settle.get("busy_reason")  # "cleared" or "capped"; capped = the scene never settled
                after = await S._run_sync(_pose)
                if after.get("map_id") != before.get("map_id"):
                    after = await _settle_warp(after)
                said = await S._run_sync(lambda: _box_lines() if _dialog_open() else "")
            step = {"action": a, "before": before, "after": after, "dialog": detail, "settle": settle}
            if said and not isinstance(detail, dict):
                step["said"] = said  # the page a plain press left on screen (a_until carries its own transcript)
            steps.append(step)
            executed += 1
        state_after = await S._run_sync(_state_dict)
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

# pokemon_agent's MAP_NAMES mislabels the Viridian Forest -> Pewter cluster: its table drifts
# from ID 50 on (it calls 51 "Pewter Museum 1F" when the RAM's 51 is the Viridian Forest, per
# pret/pokered). The RAM map_id is authoritative; only the NAME lookup is wrong, and we feed that
# name straight to the model. Correct the benchmark-path IDs in place so no model is handed a lie.
# Scoring already keys off map_id (milestones.py), so this is purely the player-facing name.
try:  # noqa: E402
    from pokemon_agent.memory.red import MAP_NAMES as _MAP_NAMES
    _MAP_NAMES.update({
        47: "Viridian Forest North Gate",
        50: "Viridian Forest South Gate",
        51: "Viridian Forest",
        52: "Museum 1F",
        53: "Museum 2F",
        54: "Pewter Gym",
        55: "Pewter House (Nidoran)",
        56: "Pewter Mart",
        57: "Pewter House",
        58: "Pewter Pokecenter",
    })
except Exception:
    pass

_milestones: dict = {}  # key -> turn, for the current game; cleared on /games/new


@S.app.post("/milestones")
async def post_milestone(body: dict):
    """Harness reports a newly hit milestone {key, label, turn}; stored for /stream refreshes and broadcast live."""
    key, turn = body.get("key"), body.get("turn")
    # The harness (milestones.py tracker) is the single source of truth: it posts each key exactly
    # once, at its real first turn, guarded against the boot state. So TRUST it and overwrite — a
    # stale value left by a boot false-fire or a prior session must not lock the dashboard to turn 1.
    if key and _milestones.get(key) != turn:
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
        settle = await _settle_screen(_FRAME_SETTLE_TICKS)

        def _build():
            state = _state_dict()
            png = S._get_screenshot_bytes()
            b64 = base64.b64encode(png).decode("ascii")
            ascii_text = (state.get("collision") or {}).get("ascii")
            return {"state": state, "screenshot_b64": b64, "ascii": ascii_text, "screen_text": _screen_text(), "warps": _warps(),
                    "dialog_open": _dialog_open(), "menu_open": _menu_open(), "map_loaded": (state.get("map") or {}).get("loaded", True),
                    "in_battle": S._emulator.read_u8(_red.ADDR_BATTLE_TYPE) != 0, "settle": settle}
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
