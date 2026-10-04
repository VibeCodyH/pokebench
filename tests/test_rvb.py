"""RVB category (issue #102): screenshot in, eight buttons out, nothing the harness observed.

The TAB tests here are the drift guard for the original board: the request the model gets must
read exactly as it did before categories existed.
"""
import base64
import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from PIL import Image

import categories
import providers
import qwen_red
import run_benchmark as runner

sys_path_site = str(Path(runner.HERE) / "site")
import sys  # noqa: E402
if sys_path_site not in sys.path:
    sys.path.insert(0, sys_path_site)
import build_runs  # noqa: E402


POSE = {"map_id": 2, "map_name": "Pewter City", "pos": [10, 16], "ui": False}
LEAKS = ("Pewter City", "(10,16)", "STATE", "WALKABILITY", "SCREEN TEXT", "blocked", "MAP CHANGED",
         "no movement", "said:", "map_id", "RAM")


def frame(**flags):
    image = io.BytesIO()
    Image.new("RGB", (160, 144), "red").save(image, "PNG")
    return {"state": {"map": {"map_id": 2, "map_name": "Pewter City"},
                      "player": {"position": {"x": 10, "y": 16}},
                      "collision": {"walkable": [[True] * 10 for _ in range(9)],
                                    "tile_ids": [[1] * 10 for _ in range(9)], "tileset": 9}},
            "screenshot_b64": base64.b64encode(image.getvalue()).decode(), "screen_text": "PROF.OAK: Hello!",
            "warps": [[4, 0, 51]], "dialog_open": False, "menu_open": False,
            "in_battle": False, "settle": "cleared", **flags}


class RunFixture(unittest.TestCase):
    def play(self, plans, category="rvb", budget=None, provider_name="ollama", steps_for=None, record=None,
             fail_actions_on_post=None):
        """Drive runner.run with scripted plans. A plan may be an Exception to fail that call.
        Returns (log rows, artifact dir, provider mock, posted action lists)."""
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        provider = Mock()
        provider.chat.side_effect = [p if isinstance(p, Exception) else (p, "", {"prompt": 1, "completion": 1})
                                     for p in plans]
        posted = []
        fr = frame()

        def get(url, **kwargs):
            return Mock(json=lambda: fr if url.endswith("/frame") else {"state": "running"})

        def post(url, **kwargs):
            if url.endswith("/action/traced"):
                actions = kwargs["json"]["actions"]
                posted.append(actions)
                if fail_actions_on_post == len(posted):
                    raise RuntimeError("server went away mid-batch")
                steps = steps_for(actions) if steps_for else [
                    {"action": a, "before": POSE, "after": POSE} for a in actions]
                return Mock(json=lambda: {"actions_executed": len(actions), "steps": steps,
                                          "state_after": fr["state"]}, raise_for_status=lambda: None)
            return Mock(json=lambda: {}, raise_for_status=lambda: None)

        model = {"key": "test", "api_model_id": "test", "provider": provider_name, "num_ctx": 65536, "think": "off"}
        good = sum(1 for p in plans if not isinstance(p, Exception))
        self.summary_kwargs = {}
        with patch.multiple(runner, RUNS_DIR=tmp.name, harness_fingerprint=Mock(return_value=(None, None)),
                            record_milestones=Mock(side_effect=record) if record else Mock(return_value=False),
                            save_game=Mock(return_value=None),
                            write_summary=Mock(side_effect=lambda *a, **k: self.summary_kwargs.update(k)),
                            verify_fresh_game=Mock()), \
                patch.object(runner.requests, "get", side_effect=get), \
                patch.object(runner.requests, "post", side_effect=post), \
                patch.object(runner.time, "sleep"), contextlib.redirect_stdout(io.StringIO()):
            runner.run(model, provider, "http://unused", budget=budget or good, category=category)
        artifact = next(Path(tmp.name).iterdir())
        rows = [json.loads(line) for line in (artifact / "log.jsonl").read_text().splitlines()]
        return rows, artifact, provider, posted


class RvbRequestTests(RunFixture):
    def test_model_sees_screenshot_and_its_own_words_only(self):
        rows, _, provider, _ = self.play([
            {"thought": "A title screen. Start, then A.", "actions": ["start", "a"]},
            {"thought": "Text. Press A.", "actions": ["a"]},
        ])
        first, second = provider.chat.call_args_list
        system, user, img, schema, _ = second.args
        for leak in LEAKS:
            self.assertNotIn(leak, system, leak)
            self.assertNotIn(leak, user, leak)
        self.assertNotIn("PROF.OAK", user)                       # screen text read from RAM never reaches it
        self.assertIn("turn 1: A title screen. Start, then A. -> pressed [start a]", user)
        self.assertIn("YOUR NOTES:\n(no notes yet)", user)
        self.assertEqual(schema["properties"]["actions"]["items"]["enum"], sorted(categories.RVB_BUTTONS))
        self.assertNotIn("maxItems", schema["properties"]["actions"])  # the runner holds the cap, not the backend
        self.assertTrue(base64.b64decode(img))
        self.assertIn("Buttons (strings, exactly): up, down, left, right, a, b, start, select.", system)
        self.assertNotIn("a_until_dialog_end", system)
        self.assertNotIn("walk_", system)
        # receipts: the exact text the model got, and the harness's own account, both in the log
        self.assertEqual(rows[1]["user_message"], user)
        self.assertEqual(rows[0]["category"], "rvb")
        self.assertIn("Pewter City", rows[0]["feedback"])
        self.assertEqual(rows[0]["screen_text"], "PROF.OAK: Hello!")

    def test_nothing_the_harness_saw_reaches_any_message_even_with_poisoned_feedback(self):
        # Steps that would make TAB's feedback line talk: a transcript, a blocked walk, a map
        # change, an action error. None of it may appear in any RVB system/user message.
        def steps_for(actions):
            moved = {"map_id": 51, "map_name": "Viridian Forest", "pos": [1, 2], "ui": False}
            return [{"action": actions[0], "before": POSE, "after": POSE, "dialog": None, "said": "PROF.OAK: Hello!"},
                    {"action": "a", "before": POSE, "after": POSE,
                     "dialog": {"presses": 12, "stop_reason": "closed", "text": ["OAK: Your very own", "POKéMON legend"]}},
                    {"action": "up", "before": POSE, "after": moved},
                    {"action": "b", "error": "Unknown action format: b"}]
        rows, _, provider, _ = self.play([
            {"thought": "t1", "actions": ["a", "a", "up", "b"]},
            {"thought": "t2", "actions": ["a", "a", "up", "b"]},
            {"thought": "t3", "actions": ["a"]},
        ], steps_for=steps_for)
        poison = LEAKS + ("PROF.OAK", "Viridian", "legend", "Unknown action", "error", "dialog", "x12", "51")
        for call in provider.chat.call_args_list:
            for text in (call.args[0], call.args[1]):
                for leak in poison:
                    self.assertNotIn(leak, text, leak)
        self.assertIn("turn 2: t2 -> pressed [a a up b]", provider.chat.call_args_list[2].args[1])
        # the harness kept its own account in the receipts
        self.assertIn("Viridian Forest", rows[0]["feedback"])
        self.assertIn("action error", rows[0]["feedback"])

    def test_macros_unknown_names_and_overlong_plans_retry_without_a_press(self):
        rows, _, _, posted = self.play([
            {"thought": "", "actions": ["walk_up"]},
            {"thought": "", "actions": ["press_a"]},
            {"thought": "", "actions": ["jump"]},
            {"thought": "", "actions": ["a"] * 7},
            {"thought": "", "actions": "a"},
            {"thought": "ok", "actions": ["up", "up", "a"]},
        ], budget=1)
        self.assertEqual(posted, [["up", "up", "a"]])
        rejected = [r for r in rows if r.get("turn_not_counted")]
        self.assertEqual(len(rejected), 5)
        self.assertIn("outside the allowed set", rejected[0]["model_error"])
        self.assertIn("limit is 6", rejected[3]["model_error"])
        self.assertIn("must be a list", rejected[4]["model_error"])
        self.assertEqual(rows[-1]["plan"]["actions"], ["up", "up", "a"])
        # every failed attempt carries the exact request it failed on, and its category
        for row in rejected:
            self.assertEqual(row["category"], "rvb")
            self.assertEqual(row["user_message"], rows[-1]["user_message"])  # same turn, same request

    def test_uppercase_button_names_are_rejected_not_normalized(self):
        rows, _, _, posted = self.play([{"thought": "", "actions": ["UP"]}, {"thought": "", "actions": ["up"]}], budget=1)
        self.assertEqual(posted, [["up"]])
        self.assertIn("'UP'", rows[0]["model_error"])

    def test_empty_plan_spends_the_turn_with_zero_presses(self):
        rows, _, _, posted = self.play([{"thought": "waiting", "actions": []}])
        self.assertEqual(posted, [[]])
        self.assertEqual(len(rows), 1)
        self.assertNotIn("wait_60", json.dumps(rows))
        self.assertEqual(rows[0]["feedback"].split(" did ")[1][:2], "[]")

    def test_notes_are_uncapped_and_shown_back_and_blank_does_not_clear(self):
        book = "chapter " * 300  # 2,400 chars: TAB would cut this at 600
        rows, artifact, provider, _ = self.play([
            {"thought": "t1", "actions": ["a"], "notes": book},
            {"thought": "t2", "actions": ["a"], "notes": ""},
            {"thought": "t3", "actions": ["a"], "notes": "  \n "},
            {"thought": "t4", "actions": ["a"]},
        ])
        self.assertEqual((artifact / "notes.md").read_text(), book)
        for call in provider.chat.call_args_list[1:]:
            self.assertIn(book, call.args[1])
        self.assertNotIn("notes_dropped_chars", rows[0])

    def test_oversized_notes_show_their_head_with_a_marker_and_stay_whole_on_disk(self):
        tome = "".join(f"line {i}\n" for i in range(60_000))  # ~650k chars, far past a 65k-token context
        rows, artifact, provider, _ = self.play([
            {"thought": "t1", "actions": ["a"], "notes": tome},
            {"thought": "t2", "actions": ["a"]},
        ])
        self.assertEqual((artifact / "notes.md").read_text(), tome)
        user = provider.chat.call_args_list[1].args[1]
        self.assertIn("line 0\nline 1\n", user)
        self.assertNotIn("line 59999", user)
        self.assertIn("only the first", user)
        self.assertIn("The full file is kept on disk", user)
        self.assertLess(len(user), 65536 * 4)
        self.assertGreater(rows[1]["notes_dropped_chars"], 400_000)
        self.assertEqual(rows[1]["user_message"], user)

    def test_history_is_trimmed_to_context_without_a_milestone_anchor(self):
        with patch.object(runner, "milestone_anchor_turn", side_effect=AssertionError("anchor must not be consulted in RVB")):
            rows, _, provider, _ = self.play([
                {"thought": "x" * 400_000, "actions": ["a"]},
                {"thought": "short", "actions": ["b"]},
            ])
        user = provider.chat.call_args_list[1].args[1]
        self.assertNotIn("x" * 1000, user)       # the oversized entry did not fit the 65k context
        self.assertIn("(none yet)", user)

    def test_presses_are_counted_per_turn_and_credited_at_the_press_that_hit_the_milestone(self):
        # record_milestones call order per turn: pre-turn, then one per step with a map_id, then post-turn.
        # Turn 2 has four steps; the milestone lands on its FIRST step, so it is credited at 2 + 1, not 2 + 4.
        hits = iter([False, False, False, False, False, True])
        tracker_first = {}

        def record(server, tracker, state, turn, epoch=None):
            if next(hits, False):
                tracker.first_turn.setdefault("route_1", turn)
            return False

        with patch.object(runner, "MilestoneTracker", return_value=Mock(first_turn=tracker_first)):
            rows, _, _, _ = self.play([
                {"thought": "", "actions": ["start", "a"]},
                {"thought": "", "actions": ["up", "up", "up", "a"]},
            ], record=record)
        self.assertEqual([r["presses"] for r in rows], [2, 4])
        self.assertEqual([r["presses_total"] for r in rows], [2, 6])
        self.assertEqual(self.summary_kwargs["milestone_presses"], {"route_1": 3})
        self.assertEqual(self.summary_kwargs["presses_used"], 6)
        self.assertTrue(self.summary_kwargs["presses_exact"])
        self.assertEqual(self.summary_kwargs["category"].id, "rvb")

    def test_a_failed_action_call_makes_the_press_count_a_floor_not_a_zero(self):
        rows, _, _, _ = self.play([
            {"thought": "", "actions": ["a", "a"]},
            {"thought": "", "actions": ["up"]},
            {"thought": "", "actions": ["b"]},
        ], fail_actions_on_post=2)
        self.assertEqual([r["presses"] for r in rows], [2, None, 1])
        self.assertEqual([r["presses_total"] for r in rows], [2, 2, 3])
        self.assertIn("action error", rows[1]["result"])
        self.assertEqual(self.summary_kwargs["presses_used"], 3)
        self.assertFalse(self.summary_kwargs["presses_exact"])

    def test_jev_is_refused(self):
        with self.assertRaises(ValueError):
            self.play([{"thought": "", "actions": ["a"]}], provider_name="jev")


class TabUnchangedTests(RunFixture):
    def test_tab_request_and_fallbacks_read_as_before(self):
        long_notes = "n" * 700
        rows, artifact, provider, posted = self.play([
            {"thought": "go", "actions": ["walk_up"] * 8, "notes": long_notes},
            {"thought": "idle", "actions": []},
        ], category="tab")
        system, user, _, schema, _ = provider.chat.call_args_list[1].args
        self.assertEqual(system, qwen_red.render_system("You are Qwen, a local AI playing Pokémon Red live on stream."))
        self.assertIs(schema, qwen_red.SCHEMA)
        # The whole legacy request, assembled by hand from the pre-category formula.
        state = frame()["state"]
        expected = ("NOTES:\n" + "n" * 600 + "\n\nRECENT TURNS:\n"
                    "turn 1: Pewter City (10,16) did [walk_up walk_up walk_up walk_up walk_up walk_up] -> Pewter City (10,16)"
                    " (no movement) blocked walks: walk_up x6"
                    f"\n\nSTATE:\n{qwen_red.compact(state)}\n\nSCREEN TEXT (words on screen right now):\nPROF.OAK: Hello!"
                    "\n\nWALKABILITY MAP (you are @ at E5):\n(map hidden while text is on screen)"
                    "\n\nThe screenshot is attached. Take your turn.")
        self.assertEqual(user, expected)
        self.assertEqual(posted, [["walk_up"] * 6, ["wait_60"]])
        self.assertEqual((artifact / "notes.md").read_text(), "n" * 600)
        self.assertEqual(rows[0]["category"], "tab")
        self.assertEqual(rows[0]["user_message"], provider.chat.call_args_list[0].args[1])
        self.assertEqual([r["presses"] for r in rows], [6, 0])   # wait_60 presses nothing

    def test_presses_in_counts_real_button_presses(self):
        steps = [{"action": "a_until_dialog_end", "dialog": {"presses": 37, "stop_reason": "closed"}},
                 {"action": "wait_60"}, {"action": "hold_a_30"}, {"action": "walk_up"},
                 {"action": "press_a", "error": "Unknown action format: press_a"}, {"action": "up"}]
        self.assertEqual(runner.presses_in(steps), 40)

    def test_rvb_schema_survives_provider_translation(self):
        for name in ("openai", "google", "anthropic"):
            with self.subTest(provider=name):
                schema = providers._schema_for(categories.RVB_SCHEMA, name)
                actions = schema["properties"]["actions"]
                self.assertEqual(actions["items"]["enum"], sorted(categories.RVB_BUTTONS))
                self.assertNotIn("maxItems", actions)
                self.assertNotIn("minItems", actions)
        strict = providers._schema_for(categories.RVB_SCHEMA, "openai")
        self.assertIn("notes", strict["required"])  # strict mode forces the field: blank must not clear notes
        self.assertEqual(categories.RVB_SCHEMA["required"], ["thought", "actions"])  # caller's copy untouched

    def test_calibration_runs_never_reach_the_board(self):
        with tempfile.TemporaryDirectory() as root:
            base = {"furthest_index": 3, "turns_used": 1000, "budget_turns": 1000, "termination_reason": "budget",
                    "prompt_version": "v22", "furthest_key": "route_1", "milestones": []}
            for name, extra in (("scored", {}), ("pilot", {"calibration": True}),
                                ("rvb-pilot", {"calibration": True, "prompt_version": "rvb1", "category": "rvb"})):
                d = Path(root, "runs", name)
                d.mkdir(parents=True)
                (d / "summary.json").write_text(json.dumps({**base, **extra, "run_id": name}))
            with contextlib.redirect_stdout(io.StringIO()) as out:
                build_runs.main(root)
            board = json.loads(Path(root, "site", "runs.json").read_text())
            self.assertEqual([r["run_id"] for r in board], ["scored"])
            self.assertIn("2 calibration runs excluded", out.getvalue())

    def test_summary_provenance_per_category(self):
        tracker = Mock(summary=Mock(return_value={"furthest_label": "Left the house", "furthest_index": 0}))
        provider = Mock(cost=Mock(return_value=0.0), max_tokens=None, route=None)
        model = {"key": "k", "api_model_id": "m", "provider": "ollama", "family": "f", "think": "high",
                 "num_ctx": 1, "temperature": 0.6}
        for category, version, allowed, extra in (
                (None, qwen_red.PROMPT_VERSION, sorted(qwen_red.ALLOWED), {}),
                (categories.CATEGORIES["tab"], qwen_red.PROMPT_VERSION, sorted(qwen_red.ALLOWED), {}),
                (categories.CATEGORIES["rvb"], "rvb1", sorted(categories.RVB_BUTTONS), {"calibration": True})):
            with self.subTest(category=getattr(category, "id", None)), tempfile.TemporaryDirectory() as tmp, \
                    contextlib.redirect_stdout(io.StringIO()):
                runner.write_summary(tmp, "rid", model, provider, "run", tracker, 1, 1000,
                                     {"prompt": 1, "completion": 1}, 1.0, "", None,
                                     category=category, calibration=bool(extra),
                                     presses_used=41, milestone_presses={"left_house": 9})
                summary = json.loads(Path(tmp, "summary.json").read_text())
                self.assertEqual(summary["presses_used"], 41)
                self.assertEqual(summary["milestone_presses"], {"left_house": 9})
                self.assertEqual(summary["category"], getattr(category, "id", "tab"))
                self.assertEqual(summary["prompt_version"], version)
                self.assertEqual(summary["allowed_actions"], allowed)
                self.assertEqual(summary.get("calibration"), extra.get("calibration"))
                if category is None or category.id == "tab":
                    self.assertEqual(summary["prompt_sha"], qwen_red.PROMPT_SHA)
                else:
                    self.assertEqual(summary["prompt_sha"], categories.RVB_PROMPT_SHA)
                    self.assertNotEqual(summary["prompt_sha"], qwen_red.PROMPT_SHA)


class CategoryConstantsTests(unittest.TestCase):
    def test_tab_is_the_legacy_prompt_byte_for_byte(self):
        tab = categories.CATEGORIES["tab"]
        self.assertEqual(tab.system, qwen_red.SYSTEM)
        self.assertEqual(tab.prompt_version, qwen_red.PROMPT_VERSION)
        self.assertEqual(tab.prompt_sha, qwen_red.PROMPT_SHA)
        self.assertEqual(tab.allowed, frozenset(qwen_red.ALLOWED))
        self.assertIs(tab.schema, qwen_red.SCHEMA)

    def test_rvb_prompt_has_no_game_help(self):
        for word in ("map", "RAM", "door", "warp", "walk_", "dialog", "menu", "a_until", "600"):
            self.assertNotIn(word, categories.RVB_SYSTEM, word)
        self.assertIn("__IDENTITY__", categories.RVB_SYSTEM)
        self.assertEqual(categories.RVB_PROMPT_VERSION, "rvb1")
        self.assertEqual(len(categories.RVB_PROMPT_SHA), 16)


if __name__ == "__main__":
    unittest.main()
