"""Offline harness regressions: python3 -m unittest (no emulator or network)."""
import asyncio
import base64
import contextlib
import importlib.util
import io
import json
from pathlib import Path
import sys
import tempfile
import types
import unittest
from unittest.mock import Mock, patch

from PIL import Image

import qwen_red
import run_benchmark as runner


# Import the wrapper against a RAM-only server double, without pokemon-agent/PyBoy.
async def run_sync(fn, *args):
    return fn(*args)


red = types.ModuleType("pokemon_agent.memory.red")
red.ADDR_BATTLE_TYPE, red.ADDR_JOY_IGNORE = 0xD057, 0xD730
red.GEN1_ENCODING = {0x7F: " ", **{0x80 + i: c for i, c in enumerate("ABCDEFGHIJKLMNOPQRSTUVWXYZ")}}
red.RedBlueMemoryReader = type("RedBlueMemoryReader", (), {})
red.MAP_NAMES = {}
app = types.SimpleNamespace(**{name: lambda *a, **kw: lambda fn: fn
                              for name in ("get", "post", "middleware", "on_event")})
server = types.SimpleNamespace(app=app, _execute_action=None, _run_sync=run_sync, ActionRequest=object)
package = types.ModuleType("pokemon_agent")
package.server = server
memory = types.ModuleType("pokemon_agent.memory")
memory.red = red
spec = importlib.util.spec_from_file_location("harness_server_test", Path(runner.HERE) / "serve_live.py")
live = importlib.util.module_from_spec(spec)
with patch.dict(sys.modules, {"pokemon_agent": package, "pokemon_agent.memory": memory,
                             "pokemon_agent.memory.red": red}):
    spec.loader.exec_module(live)


class RAM:
    def __init__(self):
        self.data = bytearray(65536)
        self.data[0xC3A0:0xC3A0 + 360] = bytes([1, 2, 3, 4]) * 90
        self.frames, self.presses = 0, []
        self.on_tick = self.on_press = lambda: None

    def read_u8(self, addr):
        return self.data[addr]

    def read_range(self, addr, size):
        return self.data[addr:addr + size]

    def tick(self, frames):
        for _ in range(frames):
            self.frames += 1
            self.on_tick()

    def press(self, button, frames):
        self.presses.append((button, frames))
        self.tick(frames)
        self.on_press()

    def tile(self, x, y, value=0x79):
        self.data[0xC3A0 + y * 20 + x] = value
        if value == 0x79:
            self.data[0xC3A0 + y * 20 + x + 1] = 0x7A
            self.data[0xC3A0 + (y + 1) * 20 + x] = 0x7C

    def text(self, x, y, text):
        for i, char in enumerate(text):
            self.tile(x + i, y, 0x7F if char == " " else 0x80 + ord(char) - ord("A"))


class DialogTests(unittest.TestCase):
    def setUp(self):
        self.ram = RAM()
        server._emulator = self.ram

    def test_existing_menus_never_press_a_even_without_cursor(self):
        # pokered TextBoxCoordTable, DisplayNamingScreen, MoveSelectionMenu.
        for label, corner, battle, choice in (
            ("FIGHT", (8, 12), 1, False), ("move TYPE/PP", (0, 8), 1, False),
            ("switch YES/NO", (13, 7), 2, True), ("nickname YES/NO", (14, 7), 0, True),
            ("Mart BUY/SELL", (0, 0), 0, False), ("PC", (0, 0), 0, False),
            ("name entry", (0, 4), 0, False), ("Start", (10, 0), 0, False),
        ):
            with self.subTest(menu=label):
                self.setUp()
                self.ram.data[0xD057] = battle
                self.ram.tile(*corner)
                if choice:
                    self.ram.tile(0, 12)
                    self.ram.text(15, 8, "YES")
                    self.ram.text(15, 10, "NO")
                result = asyncio.run(live._a_until_dialog_end())
                self.assertEqual(result["stop_reason"], "choice" if choice else "menu")
                self.assertEqual(result["presses"], 0)
                self.assertEqual(self.ram.presses, [])

    def test_delayed_menu_after_release_stops_and_is_traced(self):
        # T76/480/500: FIGHT appears before its cursor; T266: switch choice.
        for choice in (False, True):
            with self.subTest(choice=choice):
                self.setUp()
                self.ram.data[0xD057] = 2
                self.ram.tile(0, 12)
                self.ram.text(1, 14, "SEND OUT")
                def draw_menu():
                    if self.ram.presses and self.ram.frames >= 30:
                        self.ram.tile(*( (13, 7) if choice else (8, 12) ))
                        if choice:
                            self.ram.text(15, 8, "YES")
                            self.ram.text(15, 10, "NO")
                self.ram.on_tick = draw_menu
                result = asyncio.run(live._a_until_dialog_end())
                self.assertEqual(self.ram.presses, [("a", 1)])
                self.assertEqual(result["stop_reason"], "choice" if choice else "menu")
                self.assertEqual(len(result["trace"]), 1)
                self.assertTrue(result["trace"][0]["menu_open"])
                self.assertTrue(result["trace"][0]["ui"])
                self.assertTrue(result["trace"][0]["dialog_open"])
                self.assertEqual(result["trace"][0]["settle"], "cleared")
                json.dumps(result)

    def test_menu_during_close_grace_is_not_reported_closed(self):
        self.ram.tile(0, 12)
        self.ram.on_press = lambda: self.ram.tile(0, 12, 1)
        def draw_menu():
            if self.ram.presses and self.ram.frames >= 70:
                self.ram.tile(0, 0)
        self.ram.on_tick = draw_menu
        result = asyncio.run(live._a_until_dialog_end())
        self.assertEqual(result["stop_reason"], "menu")
        self.assertEqual(result["presses"], 1)
        self.assertTrue(result["trace"][-1]["menu_open"])

    def test_cap_and_complete_helper_transcript(self):
        self.ram.tile(0, 12)
        def next_page():
            n = len(self.ram.presses)
            self.ram.text(1, 14, "PAGE " + chr(65 + n // 26) + chr(65 + n % 26))
        self.ram.on_press = next_page
        next_page()
        result = asyncio.run(live._a_until_dialog_end())
        self.assertEqual(result["stop_reason"], "capped")
        self.assertEqual(result["presses"], 100)
        self.assertEqual(len(result["trace"]), 100)
        self.assertEqual(len(result["text"]), 101)  # T89/501: no silent 30-entry cutoff

    def test_busy_cap_does_not_press_or_claim_closed(self):
        self.ram.data[0xD730] = 0x80
        result = asyncio.run(live._a_until_dialog_end())
        self.assertEqual((result["presses"], result["stop_reason"], result["settle"]),
                         (0, "capped", "capped"))

    def test_title_alphabet_is_suppressed_but_naming_grid_is_text(self):
        self.ram.text(0, 0, "ABCDEFGHIJKLMNOP")
        self.ram.text(0, 1, "QRSTUVWXYZ")
        self.ram.data[0xC3A0 + 236] = 0x79  # actual boot screen's isolated non-border tile
        self.assertFalse(live._menu_open())
        self.assertEqual(live._screen_text(), "")
        self.ram.data[0xD057] = 1  # battle alone must not admit garbage either
        self.assertEqual(live._screen_text(), "")
        self.ram.data[0xD057] = 0
        self.ram.tile(0, 4)  # the real naming screen has a bordered alphabet grid
        self.assertTrue(live._menu_open())
        self.assertIn("ABCDEFGHIJKLMNOP", live._screen_text())

    def test_starter_pokedex_preview_remains_a_readable_ui(self):
        self.ram.data[0xC3A0:0xC3A0 + 20] = b"\x63" + b"\x64" * 18 + b"\x65"
        self.ram.tile(0, 1, 0x66)
        self.ram.tile(19, 1, 0x67)
        self.ram.text(9, 2, "SQUIRTLE")
        self.assertFalse(live._dialog_open())
        self.assertTrue(live._menu_open())
        self.assertIn("SQUIRTLE", live._screen_text())
        result = asyncio.run(live._a_until_dialog_end())
        self.assertEqual((result["presses"], result["stop_reason"]), (0, "menu"))

    def test_pokedex_list_and_overworld_party_cursor_are_menus(self):
        self.ram.tile(14, 0, 0x71)
        for r in range(1, 18):
            self.ram.tile(14, r, 0x71 if r % 2 else 0x70)
        self.assertTrue(live._menu_open())
        self.setUp()
        self.ram.tile(0, 12)
        self.ram.tile(0, 1, 0xED)
        result = asyncio.run(live._a_until_dialog_end())
        self.assertEqual((result["presses"], result["stop_reason"]), (0, "menu"))

    def test_frame_settles_script_and_text_together_and_reports_cap(self):
        server._ensure_emulator = lambda: None
        server._get_state_dict = lambda: {"sample_frame": self.ram.frames}
        server._get_screenshot_bytes = lambda: b"png"
        self.ram.data[0xD730] = 1
        def script():
            if self.ram.frames == 24:
                self.ram.data[0xD730] = 0
                self.ram.tile(0, 12)  # box exists before its first letter (T13/19)
            if self.ram.frames == 30:
                self.ram.text(1, 14, "BLUE")
        self.ram.on_tick = script
        frame = asyncio.run(live.get_frame())
        self.assertGreaterEqual(frame["state"]["sample_frame"], 42)
        self.assertTrue(frame["dialog_open"])
        self.assertFalse(frame["menu_open"])
        self.assertFalse(frame["in_battle"])
        self.assertEqual(frame["screen_text"], "BLUE")
        self.assertEqual(frame["settle"], "cleared")
        self.ram.data[0xD730] = 1
        frame = asyncio.run(live.get_frame())
        self.assertEqual(frame["settle"], "capped")

    def test_grace_wait_covers_a_script_that_starts_late(self):
        # After a box closes (grace=True) a script may idle on an unchanged tilemap before its next
        # box; a plain overworld frame with no script seen still settles fast (2 stable reads).
        def delayed_script():
            if self.ram.frames == 80:
                self.ram.data[0xD730] = 1
            if self.ram.frames == 220:
                self.ram.data[0xD730] = 0
                self.ram.tile(0, 12)
                self.ram.text(1, 14, "BLUE")
        self.ram.on_tick = delayed_script
        self.assertEqual(asyncio.run(live._settle_screen(80, grace=True)), "cleared")
        self.assertGreater(self.ram.frames, 220)
        self.assertEqual(live._screen_text(), "BLUE")


class RunnerTests(unittest.TestCase):
    def frame(self, **flags):
        image = io.BytesIO()
        Image.new("RGB", (160, 144), "red").save(image, "PNG")
        return {"state": {"map": {"map_id": 2, "map_name": "Pewter City"},
                          "player": {"position": {"x": 10, "y": 16}},
                          "collision": {"walkable": [[True] * 10 for _ in range(9)],
                                        "tile_ids": [[1] * 10 for _ in range(9)], "tileset": 9}},
                "screenshot_b64": base64.b64encode(image.getvalue()).decode(), "screen_text": "",
                "warps": [[4, 0, 51]], "dialog_open": False, "menu_open": False,
                "in_battle": False, "settle": "cleared", **flags}

    def run_turn(self, frame, steps=(), no_frames=False, retry=False):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        provider = Mock()
        plan = {"thought": "test", "actions": [st["action"] for st in steps] or ["wait_60"]}
        answer = (plan, "", {"prompt": 1, "completion": 1})
        provider.chat.side_effect = [RuntimeError("retry"), answer] if retry else [answer]
        def get(url, **kwargs):
            return Mock(json=lambda: frame if url.endswith("/frame") else {"state": "running"})
        def post(url, **kwargs):
            return Mock(json=lambda: {"actions_executed": len(steps), "steps": steps, "state_after": frame["state"]})
        model = {"key": "test", "api_model_id": "test", "provider": "ollama", "num_ctx": 65536, "think": "off"}
        with patch.multiple(runner, RUNS_DIR=tmp.name, harness_fingerprint=Mock(return_value=(None, None)),
                            record_milestones=Mock(return_value=False), save_game=Mock(return_value=None),
                            write_summary=Mock(return_value=None)), \
                patch.object(runner.requests, "get", side_effect=get), \
                patch.object(runner.requests, "post", side_effect=post), \
                patch.object(runner.time, "sleep"), contextlib.redirect_stdout(io.StringIO()):
            runner.run(model, provider, "http://unused", budget=1, no_frames=no_frames)
        artifact = next(Path(tmp.name).iterdir())
        records = [json.loads(line) for line in (artifact / "log.jsonl").read_text().splitlines()]
        return records, artifact, provider

    def test_back_at_start_feedback(self):
        def pose(y):
            return {"map_id": 2, "map_name": "Pewter City", "pos": [10, y], "ui": False}
        steps = [{"action": "walk_down", "before": pose(16), "after": pose(17)},
                 {"action": "walk_up", "before": pose(17), "after": pose(16)}]
        rows, _, _ = self.run_turn(self.frame(), steps)
        self.assertIn("(back at the starting position)", rows[0]["feedback"])
        self.assertNotIn("(no movement)", rows[0]["feedback"])

    def test_transcript_truncation_reports_exact_whole_line_count(self):
        pages = [f"{i:02d} " + "a" * 97 for i in range(32)]
        steps = [{"action": "a_until_dialog_end", "dialog": {"text": pages, "presses": 50, "stop_reason": "closed"}}]
        rows, _, _ = self.run_turn(self.frame(), steps)
        self.assertIn("(… 18 more lines not shown)", rows[0]["feedback"])
        self.assertIn(pages[13], rows[0]["feedback"])
        self.assertNotIn(pages[14], rows[0]["feedback"])
        self.assertEqual(rows[0]["steps"][0]["dialog"]["text"], pages)

    def test_blank_dialog_and_unsettled_frames_hide_map_and_log_flags(self):
        for flags, message in (({"dialog_open": True}, "(map hidden while text is on screen)"),
                               ({"settle": "capped"}, "(map hidden while frame is unsettled)"),
                               ({"menu_open": True}, "(no map: in battle or menu)")):
            with self.subTest(flags=flags):
                rows, _, provider = self.run_turn(self.frame(**flags))
                self.assertEqual(rows[0]["map"], message)
                self.assertIn(message, provider.chat.call_args.args[1])
                for k, v in flags.items():
                    self.assertEqual(rows[0][k], v)

    def test_frame_receipts_match_provider_bytes_and_no_frames(self):
        for disabled in (False, True):
            with self.subTest(no_frames=disabled):
                frame = self.frame()
                rows, artifact, provider = self.run_turn(frame, no_frames=disabled, retry=True)
                for row, call in zip(rows, provider.chat.call_args_list):
                    self.assertEqual(row["collision"], frame["state"]["collision"])
                    self.assertEqual(row["warps"], frame["warps"])
                    self.assertEqual(row["party_count"], 0)
                    if disabled:
                        self.assertIsNone(row["frame_file"])
                        self.assertFalse((artifact / "frames").exists())
                    else:
                        self.assertEqual((artifact / row["frame_file"]).read_bytes(), base64.b64decode(call.args[2]))
                if not disabled:
                    self.assertEqual(rows[-1]["frame_file"], "frames/turn-0001.png")
                    self.assertNotEqual(rows[0]["frame_file"], rows[1]["frame_file"])


class StateTests(unittest.TestCase):
    def test_gate_warps_require_collision_but_flood_fill_is_unchanged(self):
        for dest, marker in ((51, "S"), (0xFF, "D")):
            with self.subTest(dest=dest):
                grid = [[True] * 10 for _ in range(9)]
                grid[3][4] = False  # world (4,0): advertised but blocked in T152/220/315/377
                state = {"player": {"position": {"x": 4, "y": 1}},
                         "collision": {"walkable": grid, "tileset": 9, "player_cell": "E5"}}
                rendered = qwen_red.build_map(state, [[4, 0, dest], [5, 0, dest], [-100, 0, dest]])
                self.assertEqual(rendered.splitlines()[4].split()[5:7], ["#", marker])
                self.assertEqual(rendered.splitlines()[5].split()[5], "@")
        grid = [[False] * 10 for _ in range(9)]
        grid[4][4] = grid[0][0] = True
        state["collision"]["walkable"] = grid
        self.assertEqual(qwen_red.build_map(state).splitlines()[1].split()[1], "#")

    def test_pending_party_slot_and_fainted_initialized_mon(self):
        for level, max_hp in ((0, 0), (5, 0)):
            text = qwen_red.compact({"party": [{"species": "SQUIRTLE", "level": level, "hp": 0, "max_hp": max_hp}]})
            self.assertIn("party: SQUIRTLE (initializing)", text)
            self.assertNotIn("party: none", text)
        text = qwen_red.compact({"party": [{"species": "SQUIRTLE", "level": 5, "hp": 0, "max_hp": 20}]})
        self.assertIn("L5 HP 0/20", text)
        self.assertNotIn("initializing", text)


if __name__ == "__main__":
    unittest.main()
