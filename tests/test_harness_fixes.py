"""Offline harness regressions: python3 -m unittest (no emulator or network)."""
import asyncio
import base64
import contextlib
import importlib.util
import io
import itertools
import json
from pathlib import Path
import sys
import tempfile
import time
import types
import unittest
from unittest.mock import Mock, patch

from PIL import Image
import requests
import urllib3

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

    def test_level_up_stats_box_is_pressed_through_not_stalled(self):
        # muse-glimmer-30b-20260912_204805 lost 118 turns to this: the level-up box draws a
        # bordered window, so _menu_open() reported it and the helper returned 0 presses while
        # the screen sat there. Only A clears it, so the run livelocked until the model
        # happened to send a bare press_a instead.
        self.ram.data[0xD057] = 1
        self.ram.tile(0, 12)                                    # "grew to level N!" text box
        self.ram.tile(9, 2)                                     # the stats window border
        for i, label in enumerate(("ATTACK", "DEFENSE", "SPEED", "SPECIAL")):
            self.ram.text(11, 3 + i * 2, label)
        self.ram.text(1, 14, "GREW TO LEVEL")

        def dismiss():                                          # A takes the whole thing down
            self.ram.tile(0, 12, 1)
            self.ram.tile(9, 2, 1)
        self.ram.on_press = dismiss
        result = asyncio.run(live._a_until_dialog_end())
        self.assertEqual(self.ram.presses, [("a", 1)])
        self.assertEqual((result["presses"], result["stop_reason"]), (1, "closed"))

    def test_status_page_with_the_same_labels_stays_a_readable_ui(self):
        # The STATUS page shows the same four labels but no text box, so it is displaying for
        # the model to read, not waiting to be dismissed. Guards the dialog_open half of the
        # level-up check: drop it and the helper mashes A through a page it should leave up.
        self.ram.tile(9, 2)
        for i, label in enumerate(("ATTACK", "DEFENSE", "SPEED", "SPECIAL")):
            self.ram.text(11, 3 + i * 2, label)
        result = asyncio.run(live._a_until_dialog_end())
        self.assertEqual((result["presses"], result["stop_reason"]), (0, "menu"))
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
        # #32: the page stays READABLE (_screen_text above) but a_until no longer refuses to
        # touch it. Nothing here ever closes the page, so it presses to the dex cap and then
        # reports the menu -- the Start-menu dex, where A only plays the cry, costs this much
        # and no more.
        result = asyncio.run(live._a_until_dialog_end())
        self.assertEqual((result["presses"], result["stop_reason"]),
                         (live._DEX_PAGE_PRESS_CAP, "menu"))

    def test_dex_data_page_is_pressed_through_when_a_closes_it(self):
        # The starter pick: two text pages, then it closes into the Yes/No. Grok 4.6 lost turns
        # 16-18 of azure-grok-4-6-20260917_001630 to this returning 0 presses (#32).
        self.ram.data[0xC3A0:0xC3A0 + 20] = b"\x63" + b"\x64" * 18 + b"\x65"
        self.ram.tile(0, 1, 0x66)
        self.ram.tile(19, 1, 0x67)
        self.assertTrue(live._dex_data_page(self.ram.read_range(0xC3A0, 360)))

        def close():
            self.ram.data[0xC3A0:0xC3A0 + 20] = bytes([1, 2, 3, 4]) * 5
        self.ram.on_press = close
        result = asyncio.run(live._a_until_dialog_end())
        self.assertEqual((result["presses"], result["stop_reason"]), (1, "closed"))

    def test_dex_list_is_never_pressed_through(self):
        # Same border, but the column-14 divider means this is the LIST, where A opens an entry
        # rather than advancing text. _dex_data_page must reject it or a_until would walk the dex.
        self.ram.data[0xC3A0:0xC3A0 + 20] = b"\x63" + b"\x64" * 18 + b"\x65"
        self.ram.tile(0, 1, 0x66)
        self.ram.tile(19, 1, 0x67)
        self.ram.data[0xC3A0 + 14] = 0x71
        for r in range(1, 18):
            self.ram.data[0xC3A0 + r * 20 + 14] = 0x71 if r % 2 else 0x70
        self.assertFalse(live._dex_data_page(self.ram.read_range(0xC3A0, 360)))
        result = asyncio.run(live._a_until_dialog_end())
        self.assertEqual((result["presses"], result["stop_reason"]), (0, "menu"))

    def test_open_dialog_is_pressed_even_when_the_screen_never_settles(self):
        # #45: the Viridian Mart parcel clerk. The pre-loop settle capped, so a_until broke with
        # 0 presses while a text box was open on screen, and GPT-6 Astra stood there for three
        # turns. _dialog_open reads the box corner from RAM, so a true reading means the box is
        # really drawn -- the empty-frame race the settle guard exists for cannot be live.
        self.ram.data[0xD730] = 0x80          # permanently busy: every settle comes back capped
        self.ram.tile(0, 12)                  # ... with a real text box on screen

        def close():
            self.ram.tile(0, 12, 1)
        self.ram.on_press = close
        result = asyncio.run(live._a_until_dialog_end())
        # The press is the fix. It still reports "capped" rather than "closed", because a screen
        # that never settles is a screen we cannot claim anything about -- the invariant
        # test_busy_cap_does_not_press_or_claim_closed protects. Before this change it reported
        # the same "capped" with ZERO presses, which is what cost Astra the turns.
        self.assertEqual(self.ram.presses, [("a", 1)])
        self.assertEqual((result["presses"], result["stop_reason"]), (1, "capped"))
        self.assertFalse(live._dialog_open())

    def test_unsettled_dialog_that_never_clears_is_bounded(self):
        # The same path with nothing ever closing the box must not burn all _A_UNTIL_CAP presses
        # at full speed: the post-press settle caps too, so only the dedicated cap stops it.
        self.ram.data[0xD730] = 0x80
        self.ram.tile(0, 12)
        result = asyncio.run(live._a_until_dialog_end())
        self.assertEqual((result["presses"], result["stop_reason"]),
                         (live._UNSETTLED_PRESS_CAP, "capped"))
        self.assertLess(result["presses"], live._A_UNTIL_CAP)

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
    def test_gate_warps_require_collision_and_map_is_raw_walkability(self):
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
        self.assertEqual(qwen_red.build_map(state).splitlines()[1].split()[1], ".")  # walkable, no route in window: still "."

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


class PlanErrorTests(unittest.TestCase):
    def test_invalid_plan_error_carries_raw_output(self):
        import providers
        for content, expect in (("", ""), ("{oops", "{oops"), (None, "None"), ("[1]", "[1]")):
            with self.assertRaises(ValueError) as caught:
                providers._plan(content)
            self.assertEqual(caught.exception.raw_output, expect)

    def test_door_rule_does_not_contradict_exit_mat_rule(self):
        text = qwen_red.SYSTEM
        self.assertNotIn("entrances/exits", text)
        self.assertIn("EXIT MAT", text)


class IntroAndAccountingTests(RunnerTests):
    """2026-09-11 audit: intro coordinates presented as a place, SIGINT turn count, lost retry usage."""

    def intro_frame(self):
        frame = self.frame(map_loaded=False)
        frame["state"]["map"] = {"map_id": 38, "map_name": "Red's House 2F", "loaded": False}
        frame["state"]["player"]["position"] = {"x": 3, "y": 6}
        return frame

    def test_intro_state_has_no_place_and_no_map_change(self):
        rows, _, provider = self.run_turn(self.intro_frame(), [{"action": "press_a",
            "before": {"map_id": 0, "map_name": "Pallet Town", "pos": [0, 0], "ui": True, "loaded": False},
            "after": {"map_id": 38, "map_name": "Red's House 2F", "pos": [3, 6], "ui": True, "loaded": False}}])
        self.assertIn("map: none loaded yet (title screen or intro)", rows[0]["state"])
        self.assertNotIn("Red's House", rows[0]["state"])
        self.assertNotIn("MAP CHANGED", rows[0]["feedback"])
        self.assertIn("no map (title/intro) did [press_a] -> no map (title/intro)", rows[0]["feedback"])
        self.assertIs(rows[0]["map_loaded"], False)
        self.assertNotIn("Red's House", provider.chat.call_args.args[1].split("STATE:")[1].split("SCREEN TEXT")[0])

    def test_first_real_map_is_reported_as_loaded_not_changed(self):
        rows, _, _ = self.run_turn(self.intro_frame(), [{"action": "a_until_dialog_end",
            "before": {"map_id": 38, "map_name": "Red's House 2F", "pos": [3, 6], "ui": True, "loaded": False},
            "after": {"map_id": 38, "map_name": "Red's House 2F", "pos": [3, 6], "ui": False, "loaded": True}}])
        self.assertIn("MAP LOADED Red's House 2F", rows[0]["feedback"])
        self.assertNotIn("MAP CHANGED", rows[0]["feedback"])

    def test_loaded_map_state_is_unchanged(self):
        rows, _, _ = self.run_turn(self.frame())
        self.assertTrue(rows[0]["state"].startswith("map: Pewter City  pos {'x': 10, 'y': 16}"))
        self.assertIs(rows[0]["map_loaded"], True)

    def test_interrupt_counts_completed_turns_and_names_the_reason(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        provider = Mock()
        plan = ({"thought": "t", "actions": ["wait_60"]}, "", {"prompt": 10, "completion": 1})
        provider.chat.side_effect = [plan, plan, KeyboardInterrupt()]
        frame = self.frame()
        get = lambda url, **kw: Mock(json=lambda: frame if url.endswith("/frame") else {"state": "running"})
        post = lambda url, **kw: Mock(json=lambda: {"actions_executed": 1, "steps": [], "state_after": frame["state"]})
        model = {"key": "test", "api_model_id": "test", "provider": "ollama", "num_ctx": 65536, "think": "off"}
        summary = Mock(return_value=None)
        with patch.multiple(runner, RUNS_DIR=tmp.name, harness_fingerprint=Mock(return_value=(None, None)),
                            record_milestones=Mock(return_value=False), save_game=Mock(return_value=None),
                            write_summary=summary), \
                patch.object(runner.requests, "get", side_effect=get), \
                patch.object(runner.requests, "post", side_effect=post), \
                patch.object(runner.time, "sleep"), contextlib.redirect_stdout(io.StringIO()):
            with self.assertRaises(KeyboardInterrupt):
                runner.run(model, provider, "http://unused", budget=10, no_frames=True)
        args, kwargs = summary.call_args
        self.assertEqual(args[6], 2)  # turns_used: the third attempt never reached the emulator
        self.assertEqual(args[8], {"prompt": 20, "completion": 2})
        self.assertEqual(args[-2], "interrupted")
        self.assertEqual(args[-1], {"count": 0, "prompt": 0, "completion": 0})

    def test_failed_attempt_usage_is_logged_and_totalled(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        provider = Mock()
        bad = ValueError("Provider did not return a valid JSON plan")
        bad.raw_output, bad.usage = "", {"prompt": 7, "completion": 0}
        plan = ({"thought": "t", "actions": ["wait_60"]}, "", {"prompt": 10, "completion": 1})
        provider.chat.side_effect = [bad, plan]
        frame = self.frame()
        get = lambda url, **kw: Mock(json=lambda: frame if url.endswith("/frame") else {"state": "running"})
        post = lambda url, **kw: Mock(json=lambda: {"actions_executed": 1, "steps": [], "state_after": frame["state"]})
        model = {"key": "test", "api_model_id": "test", "provider": "ollama", "num_ctx": 65536, "think": "off"}
        summary = Mock(return_value=None)
        with patch.multiple(runner, RUNS_DIR=tmp.name, harness_fingerprint=Mock(return_value=(None, None)),
                            record_milestones=Mock(return_value=False), save_game=Mock(return_value=None),
                            write_summary=summary), \
                patch.object(runner.requests, "get", side_effect=get), \
                patch.object(runner.requests, "post", side_effect=post), \
                patch.object(runner.time, "sleep"), contextlib.redirect_stdout(io.StringIO()):
            runner.run(model, provider, "http://unused", budget=1, no_frames=True)
        artifact = next(Path(tmp.name).iterdir())
        rows = [json.loads(line) for line in (artifact / "log.jsonl").read_text().splitlines()]
        self.assertTrue(rows[0]["turn_not_counted"])
        self.assertEqual(rows[0]["tokens"], {"prompt": 7, "completion": 0})
        self.assertIn("model_s", rows[0])
        args, _ = summary.call_args
        self.assertEqual(args[6], 1)
        self.assertEqual(args[8], {"prompt": 10, "completion": 1})  # totals still exclude the failed attempt
        self.assertEqual(args[-2], "budget")
        self.assertEqual(args[-1], {"count": 1, "prompt": 7, "completion": 0})

    def test_summary_records_termination_and_failed_attempts(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        provider = Mock(max_tokens=8192, cost=Mock(return_value=0.0))
        model = {"api_model_id": "m", "provider": "ollama", "family": "f", "think": "high", "num_ctx": 1,
                 "temperature": 0.6}
        tracker = Mock(summary=Mock(return_value={"furthest_key": None, "furthest_label": None, "furthest_index": -1}))
        with contextlib.redirect_stdout(io.StringIO()):
            path = runner.write_summary(tmp.name, "id", model, provider, "run", tracker, 734, 1000,
                                        {"prompt": 1, "completion": 1}, 1.0, "", None,
                                        termination="interrupted", failed_attempts={"count": 3, "prompt": 9, "completion": 0})
        summary = json.loads(Path(path).read_text())
        self.assertEqual(summary["turns_used"], 734)
        self.assertEqual(summary["termination_reason"], "interrupted")
        self.assertEqual(summary["failed_attempts"], {"count": 3, "prompt": 9, "completion": 0})
        self.assertEqual(summary["max_output_tokens"], 8192)


class ProviderUsageTests(unittest.TestCase):
    def test_ollama_parse_failure_keeps_usage_and_reports_num_predict(self):
        import providers
        p = providers.OllamaProvider("m")
        self.assertIsNone(p.max_tokens)  # uncapped; the wire value is num_predict -1
        with patch.object(p, "_post", return_value={"message": {"content": ""}, "prompt_eval_count": 500, "eval_count": 0}):
            with self.assertRaises(ValueError) as caught:
                p.chat("s", "u", "", {}, "high")
        self.assertEqual(caught.exception.usage, {"prompt": 500, "completion": 0})
        self.assertEqual(caught.exception.raw_output, "")

    def test_openai_length_finish_keeps_usage_and_names_the_reason(self):
        import providers
        with patch.dict("os.environ", {"OPENAI_API_KEY": "test"}):
            p = providers.OpenAIProvider("m")
        body = {"choices": [{"message": {"content": "{\"thought\": \"tru"}, "finish_reason": "length"}],
                "usage": {"prompt_tokens": 300, "completion_tokens": 8192}}
        with patch.object(p, "_post_stream", return_value=body):
            with self.assertRaises(ValueError) as caught:
                p.chat("s", "u", "", {}, "high")
        self.assertIn("finish_reason=length", str(caught.exception))
        self.assertEqual(caught.exception.usage, {"prompt": 300, "completion": 8192})


class StreamParsingTests(unittest.TestCase):
    """_post_stream rebuilds the non-streaming response shape out of SSE frames, and every
    OpenAI-compatible adapter inherits OpenAIProvider.chat, so that reassembly is the whole
    surface: _tokens, _thinking and the finish_reason checks all read the shape it returns."""

    def setUp(self):
        import providers
        self.providers = providers
        with patch.dict("os.environ", {"OPENAI_API_KEY": "test"}):
            self.provider = providers.OpenAIProvider("m")

    def sse(self, body, status=200):
        """A real Response over an SSE body, so iter_lines and the decoding actually run.

        encoding starts where the adapter would leave it: get_encoding_from_headers answers
        ISO-8859-1 for any text/* type that omits a charset, which is the mojibake
        _post_stream overrides."""
        response = requests.Response()
        response.status_code = status
        response.headers["Content-Type"] = "text/event-stream"
        response.raw = urllib3.HTTPResponse(body=io.BytesIO(body.encode()),
                                            preload_content=False, status=status)
        response.encoding = requests.utils.get_encoding_from_headers(response.headers)
        return response

    def post(self, body, status=200):
        return patch.object(self.providers.requests, "post",
                            return_value=self.sse(body, status))

    def frames(self, *frames):
        # ensure_ascii=False so non-ASCII rides the wire as UTF-8 bytes, the way a backend
        # sends it. Escaped as \uXXXX it would survive any transport encoding and the
        # decoding under test would never be exercised.
        return "".join(f"data: {json.dumps(frame, ensure_ascii=False)}\n\n" for frame in frames)

    def call(self):
        return self.provider._post_stream("https://example.invalid/v1/chat/completions", {}, {})

    def test_deltas_reassemble_into_the_nonstreaming_shape(self):
        body = ": OPENROUTER PROCESSING\n\n" + self.frames(          # comment frame, not data
            {"choices": [{"delta": {"content": '{"thought": "caf', "reasoning": "first "}}]},
            # reasoning_content is where xAI and DeepSeek put it instead
            {"choices": [{"delta": {"content": '\u00e9"}', "reasoning_content": "second"},
                          "finish_reason": "stop"}]},
            # include_usage delivers this last, as its own frame with choices empty
            {"choices": [], "usage": {"prompt_tokens": 7, "completion_tokens": 9}},
        ) + "data: [DONE]\n\n"
        with self.post(body):
            result = self.call()
        choice = result["choices"][0]
        # cafe with an acute accent: Latin-1 would have mangled it into two characters
        self.assertEqual(choice["message"]["content"], '{"thought": "caf\u00e9"}')
        self.assertEqual(self.provider._thinking(choice["message"]), "first second")
        with patch.dict("os.environ", {"XAI_API_KEY": "test"}):
            xai = self.providers.XAIProvider("m")
        # xAI reads reasoning_content, so the rebuilt message has to carry it under both names
        self.assertEqual(xai._thinking(choice["message"]), "first second")
        self.assertEqual(choice["finish_reason"], "stop")
        self.assertEqual(self.provider._tokens(result["usage"]), {"prompt": 7, "completion": 9})

    def test_the_registry_timeout_becomes_a_silence_window_on_the_wire(self):
        # A models.yaml timeout is only a silence window because stream=True goes with it:
        # requests measures the gap between bytes, and an unstreamed call has none until the
        # model is done. include_usage is what stops _post_stream raising on every turn.
        with patch.dict(runner.os.environ, {"OPENAI_API_KEY": "k"}):
            provider = runner.make_provider(
                {"key": "m", "provider": "openai", "api_model_id": "x", "timeout": 90})
        self.assertEqual(provider.timeout, 90)
        body = self.frames(
            {"choices": [{"delta": {"content": "{}"}, "finish_reason": "stop"}]},
            {"choices": [], "usage": {"prompt_tokens": 1, "completion_tokens": 1}},
        ) + "data: [DONE]\n\n"
        with patch.object(self.providers.requests, "post", return_value=self.sse(body)) as post:
            provider.chat("s", "u", "", {}, "high")
        kwargs = post.call_args.kwargs
        self.assertEqual((kwargs["timeout"], kwargs["stream"]), (90, True))
        self.assertIs(kwargs["json"]["stream"], True)
        self.assertIs(kwargs["json"]["stream_options"]["include_usage"], True)

    def test_a_stream_without_usage_fails_instead_of_fabricating_zeros(self):
        # Zeros here would be recorded and priced as if they were real token counts.
        body = self.frames(
            {"choices": [{"delta": {"content": "{}"}, "finish_reason": "stop"}]},
        ) + "data: [DONE]\n\n"
        with self.post(body):
            with self.assertRaises(ValueError) as caught:
                self.call()
        self.assertIn("stream_options", str(caught.exception))

    def test_an_error_frame_aborts_the_stream(self):
        # A backend can answer 200 and then fail mid-stream; half a plan is not a plan.
        body = self.frames(
            {"choices": [{"delta": {"content": "{"}}]},
            {"error": {"message": "upstream capacity", "code": 502}},
        )
        with self.post(body):
            with self.assertRaises(ValueError) as caught:
                self.call()
        self.assertIn("upstream capacity", str(caught.exception))

    def test_an_error_frame_looks_like_an_http_failure_to_the_turn_loop(self):
        # OpenRouter answers 200 and then sends a 402 as an error frame once the request is
        # committed. The turn loop only aborts on exc.response.status_code / .text, so a bare
        # ValueError here retried a depleted key for the whole error window.
        body = self.frames(
            {"error": {"message": "Insufficient credits", "code": 402}},
        )
        with self.post(body):
            with self.assertRaises(ValueError) as caught:
                self.call()
        self.assertEqual(caught.exception.response.status_code, 402)
        self.assertIn("insufficient credits", caught.exception.response.text.lower())

    def test_unicode_line_separators_in_a_frame_do_not_split_it(self):
        # U+2028 is legal raw inside a JSON string, and str.splitlines() breaks on it. Without an
        # explicit delimiter the frame was cut mid-string: the tail no longer started with
        # "data:" and the head failed to parse, so a thought containing one failed the turn.
        # CRLF framing rides along to show the trailing CR is stripped, not kept in the JSON.
        text = "one\u2028two\u2029three\u0085four"
        body = "".join(f"data: {json.dumps(frame, ensure_ascii=False)}\r\n\r\n" for frame in (
            {"choices": [{"delta": {"content": text}, "finish_reason": "stop"}]},
            {"choices": [], "usage": {"prompt_tokens": 1, "completion_tokens": 1}},
        )) + "data: [DONE]\r\n\r\n"
        with self.post(body):
            result = self.call()
        self.assertEqual(result["choices"][0]["message"]["content"], text)

    def test_an_http_error_carries_its_body_to_the_turn_loop(self):
        # The turn loop reads exc.response.text to spot the billing and auth failures it must
        # not retry, and a streamed response has not fetched the body yet when it raises.
        with self.post('{"error": {"code": "insufficient_quota"}}', status=429):
            with self.assertRaises(requests.HTTPError) as caught:
                self.call()
        self.assertIn("insufficient_quota", caught.exception.response.text)


class RunawayCallTests(StreamParsingTests):
    """#47: the silence window cannot end a stream that keeps arriving. gpt-6-astra held one
    turn open for over ten minutes at ~37 KB/s with a 90s poll re-arming on every chunk."""

    def clock(self, step):
        """monotonic() readings that advance a fixed amount per call. The first reading sets
        the deadline, so with step=10 and max_call_s=25 the third loop check is the one that
        crosses it -- before the usage frame, which is what makes the raise unambiguous."""
        ticks = itertools.count(0, step)
        return patch.object(self.providers.time, "monotonic", side_effect=lambda: next(ticks))

    def endless(self):
        """Three content frames and then a perfectly good ending. A deadline that fails to
        fire therefore returns a valid result rather than erroring for some other reason."""
        return self.frames(
            {"choices": [{"delta": {"content": "aaa", "reasoning": "thinking "}}]},
            {"choices": [{"delta": {"content": "bbb"}}]},
            {"choices": [{"delta": {"content": "ccc"}, "finish_reason": "stop"}]},
            {"choices": [], "usage": {"prompt_tokens": 7, "completion_tokens": 9}},
        ) + "data: [DONE]\n\n"

    def test_a_stream_that_keeps_delivering_is_cut_at_max_call_s(self):
        self.provider.max_call_s = 25
        with self.post(self.endless()), self.clock(10):
            with self.assertRaises(TimeoutError) as caught:
                self.call()
        self.assertIn("max_call_s=25", str(caught.exception))

    def test_the_cut_is_retryable_and_carries_what_the_model_was_emitting(self):
        """No .response is the whole contract with the turn loop: it reads status None and an
        empty body, so it backs off and replays the turn instead of aborting the run the way
        it must for a 401/402/403. raw_output is the only record of WHY the call ran away."""
        self.provider.max_call_s = 25
        with self.post(self.endless()), self.clock(10):
            with self.assertRaises(TimeoutError) as caught:
                self.call()
        self.assertIsNone(getattr(caught.exception, "response", None))
        self.assertEqual(caught.exception.raw_output, "thinking aaa")

    def test_a_stream_that_finishes_in_time_is_untouched(self):
        """The control. Same body, same tiny cap, a clock that does not advance: if the guard
        fired on anything other than elapsed time this would fail too."""
        self.provider.max_call_s = 25
        with self.post(self.endless()), self.clock(0):
            result = self.call()
        self.assertEqual(result["usage"], {"prompt_tokens": 7, "completion_tokens": 9})
        self.assertEqual(result["choices"][0]["message"]["content"], "aaabbbccc")

    def test_the_default_clears_the_worst_call_ever_measured(self):
        """403.1s is the longest SUCCESSFUL call in any run on the board (azure-grok-4-3).
        A default under that turns a slow model into provider_error, which is barred from the
        leaderboard -- so tightening belongs on the row, not here."""
        self.assertGreaterEqual(self.providers.Provider.__init__.__kwdefaults__["max_call_s"], 806)

    def test_a_nonsense_cap_is_rejected_at_construction(self):
        for bad in (0, -1, float("inf")):
            with self.subTest(bad=bad), patch.dict("os.environ", {"OPENAI_API_KEY": "test"}):
                with self.assertRaises(ValueError):
                    self.providers.OpenAIProvider("m", max_call_s=bad)

    def test_a_row_can_tighten_the_cap(self):
        """make_provider must actually forward it; the knob is useless in yaml alone."""
        row = {"provider": "openai", "api_model_id": "m", "max_call_s": 300,
               "input_cost_per_mtok": 1.0, "output_cost_per_mtok": 2.0}
        with patch.dict("os.environ", {"OPENAI_API_KEY": "test"}):
            self.assertEqual(runner.make_provider(row).max_call_s, 300)

    def test_the_astra_row_is_capped(self):
        """The row the guard was written for. Its worst successful call was 26.0s."""
        config = Path(runner.__file__).resolve().parent / "models.yaml"
        row = next(m for m in runner.yaml.safe_load(config.read_text())["models"]
                   if m["key"] == "azure-gpt-6-astra")
        self.assertEqual(row["max_call_s"], 300)


class VertexClaudeTests(unittest.TestCase):
    """Claude on Google Cloud is AnthropicProvider with the transport swapped. The tests that
    matter are the two edits Google requires and the claim that nothing ELSE differs, because
    a Vertex row is only worth putting on the board if it played the same game."""

    FAKE_ADC = {"type": "authorized_user", "client_id": "cid", "client_secret": "sec",
                "refresh_token": "rt"}

    def setUp(self):
        import providers
        self.providers = providers
        self.creds = Path(tempfile.mkdtemp()) / "adc.json"
        self.creds.write_text(json.dumps(self.FAKE_ADC))

    def make(self, **kw):
        kw.setdefault("project", "proj-1")
        kw.setdefault("credentials_path", str(self.creds))
        return self.providers.VertexAnthropicProvider("claude-fable-5-1", **kw)

    def test_endpoint_matches_googles_documented_url_for_each_endpoint_type(self):
        base = "/v1/projects/proj-1/locations/{}/publishers/anthropic/models/claude-fable-5-1:rawPredict"
        for region, host in (("global", "aiplatform.googleapis.com"),
                             ("us", "aiplatform.us.rep.googleapis.com"),
                             ("eu", "aiplatform.eu.rep.googleapis.com"),
                             ("us-east5", "us-east5-aiplatform.googleapis.com")):
            with self.subTest(region=region):
                self.assertEqual(self.make(region=region)._endpoint(),
                                 f"https://{host}" + base.format(region))

    def test_dispatch_moves_model_to_the_url_and_version_into_the_body(self):
        provider = self.make()
        sent = {}
        with patch.object(provider, "_post", side_effect=lambda u, p, h: sent.update(
                url=u, payload=p, headers=h) or {"content": []}), \
             patch.object(provider, "_access_token", return_value="tok"):
            provider._dispatch({"model": "claude-fable-5-1", "max_tokens": 4000})
        self.assertNotIn("model", sent["payload"])   # Google 400s on the field
        self.assertEqual(sent["payload"]["anthropic_version"], "vertex-2023-10-16")
        self.assertEqual(sent["headers"]["Authorization"], "Bearer tok")
        self.assertNotIn("x-api-key", sent["headers"])
        self.assertIn("/models/claude-fable-5-1:rawPredict", sent["url"])

    def test_dispatch_does_not_mutate_the_payload_it_was_handed(self):
        provider = self.make()
        payload = {"model": "claude-fable-5-1", "max_tokens": 4000}
        with patch.object(provider, "_post", return_value={"content": []}), \
             patch.object(provider, "_access_token", return_value="tok"):
            provider._dispatch(payload)
        self.assertEqual(payload, {"model": "claude-fable-5-1", "max_tokens": 4000})

    def test_the_prompt_sent_to_google_is_the_one_sent_to_anthropic(self):
        """The comparability claim, asserted rather than asserted-in-a-comment: build both
        payloads from the same inputs and diff them. Only the two documented edits may differ.
        If a future change touches chat() for one path only, this is what reds."""
        import providers
        captured = {}

        def grab(name):
            def _post(url, payload, headers):
                captured[name] = payload
                return {"content": [{"type": "text", "text": "{}"}],
                        "usage": {"input_tokens": 1, "output_tokens": 1}}
            return _post

        with patch.dict("os.environ", {"ANTHROPIC_API_KEY": "test"}):
            first = providers.AnthropicProvider("claude-fable-5-1", thinking_style="adaptive",
                                                max_tokens=4000)
        vertex = self.make(thinking_style="adaptive", max_tokens=4000)
        for name, provider in (("anthropic", first), ("vertex", vertex)):
            with patch.object(provider, "_post", side_effect=grab(name)), \
                 patch.object(vertex, "_access_token", return_value="tok"):
                with contextlib.suppress(Exception):   # the fake body is not a valid plan
                    provider.chat("sys", "user", "aW1n", {"type": "object"}, "high")

        google, anthropic = dict(captured["vertex"]), dict(captured["anthropic"])
        self.assertEqual(anthropic.pop("model"), "claude-fable-5-1")
        self.assertEqual(google.pop("anthropic_version"), "vertex-2023-10-16")
        self.assertEqual(google, anthropic)

    def test_the_token_is_refreshed_early_and_reused_until_then(self):
        """A Google access token lives an hour and a run lasts several. Refreshing ON the 401
        would not work: the turn loop treats 401 as non-retryable and aborts the whole run."""
        provider = self.make()
        calls = []

        def fake_post(url, timeout, data):
            calls.append(data["grant_type"])
            return Mock(json=lambda: {"access_token": f"tok{len(calls)}", "expires_in": 3600},
                        raise_for_status=lambda: None)

        with patch.object(self.providers.requests, "post", side_effect=fake_post):
            self.assertEqual(provider._access_token(), "tok1")
            self.assertEqual(provider._access_token(), "tok1")     # cached, no second mint
            self.assertEqual(len(calls), 1)
            provider._token_expires = 0                            # as if the window elapsed
            self.assertEqual(provider._access_token(), "tok2")
        self.assertEqual(calls, ["refresh_token", "refresh_token"])

    def test_expiry_is_set_five_minutes_before_google_says(self):
        provider = self.make()
        with patch.object(self.providers.requests, "post", return_value=Mock(
                json=lambda: {"access_token": "t", "expires_in": 3600},
                raise_for_status=lambda: None)):
            provider._access_token()
        self.assertAlmostEqual(provider._token_expires - time.time(), 3300, delta=5)

    def test_a_missing_or_wrong_shaped_credential_file_says_what_to_run(self):
        missing = self.make(credentials_path=str(self.creds.parent / "nope.json"))
        with self.assertRaises(ValueError) as caught:
            missing._access_token()
        self.assertIn("gcloud auth application-default login", str(caught.exception))

        self.creds.write_text(json.dumps({"type": "service_account"}))
        with self.assertRaises(ValueError) as caught:
            self.make()._access_token()
        self.assertIn("service_account", str(caught.exception))

    def test_a_row_without_a_project_fails_before_the_run_starts(self):
        """make_provider is called at launch precisely so a misconfigured row does not die on
        turn 1 with a recording already running."""
        with patch.dict("os.environ", {"GOOGLE_CLOUD_PROJECT": ""}):
            with self.assertRaises(ValueError) as caught:
                self.providers.VertexAnthropicProvider("claude-fable-5-1")
        self.assertIn("GOOGLE_CLOUD_PROJECT", str(caught.exception))

    def test_the_fable_row_is_capped_the_way_astra_is(self):
        """claude-opus-5 ran uncapped at 798 output tokens a turn and cost $16.94 for 283
        turns. This row is the fix for that, so the cap is the thing worth pinning."""
        config = Path(runner.__file__).resolve().parent / "models.yaml"
        row = next(m for m in runner.yaml.safe_load(config.read_text())["models"]
                   if m["key"] == "vertex-claude-fable-5-1")
        self.assertEqual(row["provider"], "vertex")
        self.assertEqual(row["api_model_id"], "claude-fable-5-1")
        self.assertEqual(row["thinking_style"], "adaptive")
        self.assertEqual(row["max_output_tokens"], 4000)
        self.assertEqual((row["input_cost_per_mtok"], row["output_cost_per_mtok"]), (10.0, 50.0))
        self.assertNotIn("region", row)          # global: no 10% regional premium
        with patch.dict("os.environ", {"GOOGLE_CLOUD_PROJECT": "p"}):
            self.assertEqual(runner.make_provider(row).thinking_style, "adaptive")

    def test_the_first_party_fable_row_carries_the_same_caps(self):
        """The row that can actually run today: Google gives this project zero partner-model
        quota. Both Fable seats must be configured identically or a later Vertex run would not
        be comparable to the one that goes on the board first."""
        config = Path(runner.__file__).resolve().parent / "models.yaml"
        rows = {m["key"]: m for m in runner.yaml.safe_load(config.read_text())["models"]}
        first, vertex = rows["claude-fable-5-1"], rows["vertex-claude-fable-5-1"]
        self.assertEqual(first["provider"], "anthropic")
        for field in ("api_model_id", "context", "think", "thinking_style",
                      "max_output_tokens", "max_call_s",
                      "input_cost_per_mtok", "output_cost_per_mtok"):
            with self.subTest(field=field):
                self.assertEqual(first[field], vertex[field])
        with patch.dict("os.environ", {"ANTHROPIC_API_KEY": "test"}):
            provider = runner.make_provider(first)
        self.assertEqual(provider.max_tokens, 4000)
        self.assertTrue(provider.cache_system)   # $0.25/M cache hits are 2.5% of base input


class MaxOutputTokensTests(unittest.TestCase):
    """Models run uncapped by default: a truncated plan is a harness artifact in the results,
    not a fact about the model. The providers that allow it simply omit the field; ollama
    sends -1; Anthropic is the one API that requires a number. A row may still set a ceiling
    explicitly, which is the only way to raise Anthropic's."""

    def write_registry(self, **overrides):
        row = {"key": "m", "provider": "openai", "api_model_id": "x", "family": "f", **overrides}
        handle = tempfile.NamedTemporaryFile("w", suffix=".yaml", delete=False)
        with handle:
            json.dump({"models": [row]}, handle)  # JSON is valid YAML
        self.addCleanup(Path(handle.name).unlink)
        return handle.name

    def test_absent_means_uncapped(self):
        model = runner.load_model("m", self.write_registry())
        self.assertIsNone(model.get("max_output_tokens"))
        with patch.dict(runner.os.environ, {"OPENAI_API_KEY": "k"}):
            self.assertIsNone(runner.make_provider(model).max_tokens)

    def test_null_is_not_the_context_trap(self):
        # context: null raises, because the key is present and .get never sees the default.
        # max_output_tokens has to treat an explicit null as "no ceiling".
        model = runner.load_model("m", self.write_registry(max_output_tokens=None))
        with patch.dict(runner.os.environ, {"OPENAI_API_KEY": "k"}):
            self.assertIsNone(runner.make_provider(model).max_tokens)

    def test_uncapped_openai_omits_the_field_entirely(self):
        import providers
        with patch.dict(runner.os.environ, {"OPENAI_API_KEY": "k"}):
            p = providers.OpenAIProvider("m")
        sent = {}
        body = {"choices": [{"message": {"content": "{}"}, "finish_reason": "stop"}],
                "usage": {"prompt_tokens": 1, "completion_tokens": 1}}
        with patch.object(p, "_post_stream", side_effect=lambda url, payload, *a: sent.update(payload) or body):
            p.chat("s", "u", "", {}, "high")
        self.assertNotIn("max_completion_tokens", sent)

    def test_uncapped_ollama_sends_minus_one(self):
        import providers
        p = providers.OllamaProvider("m")
        sent = {}
        body = {"message": {"content": "{}"}, "prompt_eval_count": 1, "eval_count": 1}
        with patch.object(p, "_post", side_effect=lambda url, payload, *a: sent.update(payload) or body):
            p.chat("s", "u", "", {}, "high")
        self.assertEqual(sent["options"]["num_predict"], -1)

    def test_anthropic_requires_a_number_so_it_keeps_a_default(self):
        import providers
        with patch.dict(runner.os.environ, {"ANTHROPIC_API_KEY": "k"}):
            self.assertEqual(providers.AnthropicProvider("m").max_tokens,
                             providers.AnthropicProvider.DEFAULT_MAX_TOKENS)
            self.assertEqual(providers.AnthropicProvider("m", max_tokens=64000).max_tokens, 64000)

    def test_set_value_reaches_the_wire_not_just_the_attribute(self):
        model = runner.load_model("m", self.write_registry(max_output_tokens=16384))
        with patch.dict(runner.os.environ, {"OPENAI_API_KEY": "k"}):
            provider = runner.make_provider(model)
        self.assertEqual(provider.max_tokens, 16384)
        sent = {}
        body = {"choices": [{"message": {"content": "{}"}, "finish_reason": "stop"}],
                "usage": {"prompt_tokens": 1, "completion_tokens": 1}}
        with patch.object(provider, "_post_stream",
                          side_effect=lambda url, payload, *a: sent.update(payload) or body):
            provider.chat("s", "u", "", {}, "high")
        self.assertEqual(sent["max_completion_tokens"], 16384)

    def test_google_set_value_reaches_the_wire(self):
        import providers
        with patch.dict(runner.os.environ, {"GEMINI_API_KEY": "k"}):
            bounded = providers.GoogleProvider("m", max_tokens=16384)
            unbounded = providers.GoogleProvider("m")
        body = {"candidates": [{"content": {"parts": [{"text": "{}"}]}, "finishReason": "STOP"}],
                "usageMetadata": {"promptTokenCount": 1, "candidatesTokenCount": 1}}
        for provider, expected in ((bounded, 16384), (unbounded, None)):
            sent = {}
            with patch.object(provider, "_post",
                              side_effect=lambda url, payload, *a: sent.update(payload) or body):
                provider.chat("s", "u", "", {}, "high")
            self.assertEqual(sent["generationConfig"].get("maxOutputTokens"), expected)

    def test_rejects_nonsense_before_a_run_starts(self):
        for bad in (0, -1, 1.5, "16k", True):
            with self.subTest(bad=bad):
                with self.assertRaises(ValueError) as caught:
                    runner.load_model("m", self.write_registry(max_output_tokens=bad))
                self.assertIn("max_output_tokens", str(caught.exception))


class DeepSeekProviderTests(unittest.TestCase):
    """DeepSeek's endpoint speaks OpenAI's wire format with two differences, and both live in
    _tune_payload: thinking is a switch on the body, and response_format only knows
    json_object. The base class must not send a strict json_schema there (the row sets
    structured_output: false), yet the request still has to force a single JSON object."""

    def make(self, **opts):
        import providers
        with patch.dict("os.environ", {"DEEPSEEK_API_KEY": "test"}):
            return providers.DeepSeekProvider("deepseek-flash", structured_output=False, **opts)

    def capture(self, p, think):
        body = {"choices": [{"message": {"content": "{\"thought\": \"ok\"}", "reasoning_content": "hmm"},
                             "finish_reason": "stop"}],
                "usage": {"prompt_tokens": 10, "completion_tokens": 20}}
        with patch.object(p, "_post_stream", return_value=body) as post:
            plan, thinking, tokens = p.chat("s", "u", "", {"type": "object"}, think)
        return post.call_args.args[1], plan, thinking, tokens

    def test_high_sends_thinking_switch_and_json_object(self):
        payload, plan, thinking, tokens = self.capture(self.make(), "high")
        self.assertEqual(payload["thinking"], {"type": "enabled"})
        self.assertEqual(payload["reasoning_effort"], "high")
        self.assertEqual(payload["response_format"], {"type": "json_object"})
        self.assertEqual(plan, {"thought": "ok"})
        self.assertEqual(tokens, {"prompt": 10, "completion": 20})

    def test_off_disables_thinking_without_a_rejected_effort_value(self):
        payload, *_ = self.capture(self.make(), "off")
        self.assertEqual(payload["thinking"], {"type": "disabled"})
        self.assertNotIn("reasoning_effort", payload)

    def test_default_leaves_thinking_to_the_api(self):
        payload, *_ = self.capture(self.make(), "default")
        self.assertNotIn("thinking", payload)
        self.assertNotIn("reasoning_effort", payload)
        self.assertEqual(payload["response_format"], {"type": "json_object"})

    def test_registry_row_constructs_the_deepseek_adapter(self):
        import providers
        with patch.dict("os.environ", {"DEEPSEEK_API_KEY": "test"}):
            p = runner.make_provider(runner.load_model("deepseek-flash"))
        self.assertIsInstance(p, providers.DeepSeekProvider)
        self.assertFalse(p.structured_output)
        self.assertEqual(p.cost({"prompt": 1_000_000, "completion": 1_000_000}), 1.5)


class AnthropicThinkingStyleTests(unittest.TestCase):
    """Anthropic has TWO mutually exclusive thinking request shapes and the API hard-400s on
    the wrong one, so getting this wrong costs a run at turn 1 rather than degrading it.
    Verified live 2026-09-17: claude-opus-5 and claude-sonnet-5 reject
    `thinking:{type:enabled,budget_tokens:N}` ("Use thinking.type.adaptive and
    output_config.effort"), while Haiku 4.5 rejects adaptive. The default must stay `budget`
    so the pre-existing Haiku row keeps working untouched."""

    def make(self, **opts):
        import providers
        with patch.dict("os.environ", {"ANTHROPIC_API_KEY": "test"}):
            return providers.AnthropicProvider("claude-test", **opts)

    def capture(self, p, think):
        body = {"content": [{"type": "thinking", "thinking": "hmm"},
                            {"type": "text", "text": "{\"thought\": \"ok\", \"actions\": []}"}],
                "stop_reason": "end_turn",
                "usage": {"input_tokens": 11, "output_tokens": 22}}
        with patch.object(p, "_post", return_value=body) as post:
            plan, thinking, tokens = p.chat("s", "u", "aGk=", {"type": "object"}, think)
        return post.call_args.args[1], plan, thinking, tokens

    def test_adaptive_sends_effort_and_never_a_token_budget(self):
        payload, plan, thinking, tokens = self.capture(self.make(thinking_style="adaptive"), "high")
        self.assertEqual(payload["thinking"], {"type": "adaptive"})
        self.assertEqual(payload["output_config"]["effort"], "high")
        self.assertNotIn("budget_tokens", payload["thinking"])
        # The schema still has to ride along on output_config, not get clobbered by effort.
        self.assertEqual(payload["output_config"]["format"]["type"], "json_schema")
        self.assertEqual(plan, {"thought": "ok", "actions": []})
        # Subset, not equality: the dict also carries the cache split (see
        # AnthropicPromptCacheTests), and pinning it whole here would fail for an unrelated reason.
        self.assertEqual(tokens["prompt"], 11)
        self.assertEqual(tokens["completion"], 22)

    def test_budget_is_the_default_and_still_bumps_max_tokens(self):
        p = self.make(max_tokens=4096)
        self.assertEqual(p.thinking_style, "budget")
        payload, *_ = self.capture(p, "high")
        self.assertEqual(payload["thinking"], {"type": "enabled", "budget_tokens": 8192})
        self.assertNotIn("effort", payload["output_config"])
        self.assertGreater(payload["max_tokens"], 8192)

    def test_off_disables_thinking_under_either_style(self):
        for style in ("budget", "adaptive"):
            payload, *_ = self.capture(self.make(thinking_style=style), "off")
            self.assertEqual(payload["thinking"], {"type": "disabled"}, style)
            self.assertNotIn("effort", payload["output_config"], style)

    def test_an_unknown_style_fails_at_construction_not_at_turn_one(self):
        with self.assertRaises(ValueError):
            self.make(thinking_style="enabled")

    def test_claude_5_rows_declare_adaptive_and_haiku_keeps_the_default(self):
        import providers
        with patch.dict("os.environ", {"ANTHROPIC_API_KEY": "test"}):
            opus = runner.make_provider(runner.load_model("claude-opus-5"))
            sonnet = runner.make_provider(runner.load_model("claude-sonnet-5"))
        self.assertIsInstance(opus, providers.AnthropicProvider)
        self.assertEqual(opus.thinking_style, "adaptive")
        self.assertEqual(sonnet.thinking_style, "adaptive")
        # $5/MTok in + $25/MTok out, read off the pricing page rather than back-computed.
        self.assertEqual(opus.cost({"prompt": 1_000_000, "completion": 1_000_000}), 30.0)
        self.assertEqual(sonnet.cost({"prompt": 1_000_000, "completion": 1_000_000}), 12.0)

    def test_thinking_style_is_not_passed_to_non_anthropic_rows(self):
        """make_provider whitelists kwargs per adapter; leaking this one would TypeError."""
        row = dict(runner.load_model("or-gpt-5.6-sol"), thinking_style="adaptive")
        with patch.dict("os.environ", {"OPENROUTER_API_KEY": "test"}):
            runner.make_provider(row)  # must not raise


class JevDecisionProviderTests(unittest.TestCase):
    """Jev is the only seat that is not a chat model: a different endpoint, a {state, questions}
    body, and a typed choice back instead of prose. Each test below pins one thing that would
    otherwise fail silently rather than loudly -- a dropped image looks like a working run, and
    a plan carrying six actions would quietly give this seat six times the moves per turn."""

    RESPONSE = {  # captured verbatim from the live endpoint, 2026-09-20
        "model": "typesafe/jev-1.13-20260917",
        "answers": {"action": {
            "type": "choice", "choice": "walk_up", "confidence": 0.78,
            "probabilities": {"walk_right": 0.01, "walk_up": 0.83,
                              "walk_down": 0.01, "walk_left": 0.15}}},
        "usage": {"input_tokens": 405, "output_tokens": 50, "cost": 0.00001701},
    }

    def _provider(self):
        import providers
        self.providers = providers
        with patch.dict("os.environ", {"OPENROUTER_API_KEY": "test"}):
            return providers.get_provider(
                "jev", "typesafe/jev-1.13",
                input_cost_per_mtok=0.042, output_cost_per_mtok=0.0)

    def test_one_action_per_turn(self):
        """A choice question returns exactly one option. If this ever grew a list, this seat
        would silently start taking up to six moves a turn like the chat seats do."""
        provider = self._provider()
        with patch.object(self.providers.JevDecisionProvider, "_post", return_value=self.RESPONSE):
            plan, _, _ = provider.chat("SYS", "STATE", "IMAGEB64", {}, "high")
        self.assertEqual(plan["actions"], ["walk_up"])

    def test_screenshot_never_reaches_the_request(self):
        """Jev takes no image. Sending one would either 400 or, worse, be ignored while the
        run's receipts implied the model could see."""
        provider = self._provider()
        with patch.object(self.providers.JevDecisionProvider, "_post",
                          return_value=self.RESPONSE) as post:
            provider.chat("SYS", "STATE", "IMAGEB64", {}, "high")
        body = post.call_args[0][1]
        self.assertNotIn("IMAGEB64", json.dumps(body))
        self.assertEqual(body["state"], "SYS\n\nSTATE")

    def test_every_allowed_action_is_offered(self):
        """`criteria` IS the prompt for a choice question, so a missing key does not just omit
        documentation, it removes the option from the model's ballot entirely."""
        provider = self._provider()
        with patch.object(self.providers.JevDecisionProvider, "_post",
                          return_value=self.RESPONSE) as post:
            provider.chat("SYS", "STATE", "", {}, "high")
        offered = set(post.call_args[0][1]["questions"]["action"]["criteria"])
        self.assertEqual(offered, qwen_red.ALLOWED)

    def test_thought_is_lifted_from_the_response_not_invented(self):
        """The model emits no reasoning. The thought column has to be the distribution it
        actually reported, or the run log fabricates reasoning that never happened."""
        provider = self._provider()
        with patch.object(self.providers.JevDecisionProvider, "_post", return_value=self.RESPONSE):
            plan, thinking, _ = provider.chat("SYS", "STATE", "", {}, "high")
        self.assertEqual(thinking, "")
        self.assertIn("no reasoning", plan["thought"])
        self.assertIn("walk_up 0.83", plan["thought"])
        self.assertIn("confidence 0.78", plan["thought"])

    def test_cost_matches_the_endpoint_own_figure(self):
        """Guards the models.yaml rate against the price the API itself charged for this call."""
        provider = self._provider()
        with patch.object(self.providers.JevDecisionProvider, "_post", return_value=self.RESPONSE):
            _, _, tokens = provider.chat("SYS", "STATE", "", {}, "high")
        self.assertAlmostEqual(provider.cost(tokens), self.RESPONSE["usage"]["cost"], places=9)

    def test_missing_choice_raises_with_usage_attached(self):
        """A refusal still costs input tokens; the runner logs them from the exception."""
        provider = self._provider()
        empty = {"answers": {}, "usage": {"input_tokens": 9, "output_tokens": 0}}
        with patch.object(self.providers.JevDecisionProvider, "_post", return_value=empty):
            with self.assertRaises(ValueError) as caught:
                provider.chat("SYS", "STATE", "", {}, "high")
        self.assertEqual(caught.exception.usage, {"prompt": 9, "completion": 0})


class AnthropicPromptCacheTests(unittest.TestCase):
    """Anthropic is the only provider here that has to be ASKED to cache; the rest do it
    automatically. Two ways enabling it could quietly corrupt the receipts, both covered:
    `input_tokens` stops counting the cached prefix, so tokens_in would drop ~1.3k a turn and
    stop meaning what it means on every other row; and cost priced at the flat input rate
    would ignore the 1.25x write / 0.1x read tiers it just opted into."""

    def make(self, **opts):
        import providers
        with patch.dict("os.environ", {"ANTHROPIC_API_KEY": "test"}):
            return providers.AnthropicProvider(
                "claude-test", input_cost_per_mtok=5.0, output_cost_per_mtok=25.0, **opts)

    def capture(self, p, usage):
        body = {"content": [{"type": "text", "text": "{\"thought\": \"ok\", \"actions\": []}"}],
                "stop_reason": "end_turn", "usage": usage}
        with patch.object(p, "_post", return_value=body) as post:
            _, _, tokens = p.chat("SYS", "u", "aGk=", {"type": "object"}, "high")
        return post.call_args.args[1], tokens

    def test_system_is_sent_as_a_cacheable_block(self):
        payload, _ = self.capture(self.make(), {"input_tokens": 1, "output_tokens": 1})
        self.assertEqual(payload["system"],
                         [{"type": "text", "text": "SYS",
                           "cache_control": {"type": "ephemeral"}}])

    def test_opting_out_sends_a_plain_string_system(self):
        payload, _ = self.capture(self.make(cache_system=False),
                                  {"input_tokens": 1, "output_tokens": 1})
        self.assertEqual(payload["system"], "SYS")

    def test_cached_prefix_still_counts_toward_tokens_in(self):
        """The regression that would silently shrink tokens_in on every cached turn."""
        _, tokens = self.capture(self.make(), {
            "input_tokens": 4700, "cache_read_input_tokens": 1298, "output_tokens": 300})
        self.assertEqual(tokens["prompt"], 5998)  # what the model saw, not just the uncached part
        self.assertEqual(tokens["cache_read"], 1298)
        self.assertEqual(tokens["cache_write"], 0)

    def test_cost_applies_the_read_and_write_multipliers(self):
        p = self.make()
        # 1M uncached in + 1M cache reads at 0.1x + 1M writes at 1.25x + 1M out.
        cost = p.cost({"prompt": 3_000_000, "completion": 1_000_000,
                       "cache_read": 1_000_000, "cache_write": 1_000_000})
        self.assertAlmostEqual(cost, 5.0 + 0.5 + 6.25 + 25.0)

    def test_cost_matches_the_base_estimate_when_nothing_was_cached(self):
        p = self.make()
        flat = {"prompt": 1_000_000, "completion": 1_000_000}
        self.assertAlmostEqual(p.cost(flat), 30.0)
        self.assertAlmostEqual(p.cost(dict(flat, cache_read=0, cache_write=0)), 30.0)

    def test_totals_accumulate_cache_keys_the_seed_dict_never_had(self):
        """run_benchmark seeds {prompt, completion}; iterating that would drop the cache keys
        before cost() ever sees them, making the discount invisible in the summary."""
        total = {"prompt": 0, "completion": 0}
        for _ in range(3):
            for key, value in {"prompt": 10, "completion": 2,
                               "cache_read": 5, "cache_write": 1}.items():
                total[key] = total.get(key, 0) + value
        self.assertEqual(total, {"prompt": 30, "completion": 6,
                                 "cache_read": 15, "cache_write": 3})
