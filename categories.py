"""Leaderboard categories (issue #102).

TAB, Tool Assisted Benchmark: the harness as it has always run. RAM state as text, an ASCII
walkability map, screen text read from memory, macros like a_until_dialog_end.

RVB, Raw Vision + Buttons: the model gets the screenshot and eight buttons. Its memory is what it
wrote itself (notes, its own previous turns). Nothing the harness observed reaches it: no RAM pose,
no map, no screen text, no "blocked" feedback, no transcript. Scoring is unchanged: the RAM
milestone ladder is read by the harness, never shown to the model.

The TAB constants are the ones qwen_red.py has always exported; this module only names them.
"""
import hashlib
from dataclasses import dataclass

from qwen_red import ALLOWED as TAB_ALLOWED
from qwen_red import PROMPT_SHA as TAB_PROMPT_SHA
from qwen_red import PROMPT_VERSION as TAB_PROMPT_VERSION
from qwen_red import SCHEMA as TAB_SCHEMA
from qwen_red import SYSTEM as TAB_SYSTEM

TAB = "tab"
RVB = "rvb"

RVB_BUTTONS = ("up", "down", "left", "right", "a", "b", "start", "select")
RVB_MAX_PRESSES = 6

# No game mechanics, no map reading, no dialogue tips: the controls and the output contract.
# `notes` is deliberately unsteered. The TAB prompt says "rewrite ... Under 600 chars" and both
# runners cut it at 600, which is why every TAB run keeps one line of notes. Here the model
# decides what a notes file is for.
#
# The goal line is the one variable. rvb1 says "beat the game" while the board scores turns to
# Brock, so a model planning past Pewter (catching for Misty, picking Charmander) is scored as
# if it were lost. rvb2 names the real objective and the clock, the way a speedrunner knows the
# category. Calibration run 1 (Sol 6.1, 2026-10-04) played rvb1; the A/B against rvb2 decides
# which one scored runs use. Nothing else in the prompt changes between the two.
RVB_GOALS = {
    "game": "Overall goal: beat the game.",
    "brock": ("Goal: win the Boulder Badge from Brock in Pewter City. Your score is the number of turns "
              "you use, fewer is better, and every message tells you the turn number and your turn budget."),
}
RVB_GOAL_VERSIONS = {"game": "rvb1", "brock": "rvb2"}

RVB_SYSTEM_TEMPLATE = """__IDENTITY__ Each turn you get one screenshot of the Game Boy screen. The game keeps running in real time between turns, so the screenshot is a moment in time. Each turn you press up to six buttons, in order, one press each.

Buttons (strings, exactly): up, down, left, right, a, b, start, select.

__GOAL__

Reply with JSON only:
{"thought": "<what you see, what you intend, why>",
 "actions": ["up", "up", "a"],
 "key_moment": "<optional: one line if something notable just happened>",
 "notes": "<optional: whatever you put here becomes the full contents of your notes file, which is shown back to you every turn. Leave it out to keep the file as it is.>"}
"""

RVB_ALLOWED = frozenset(RVB_BUTTONS)
RVB_SCHEMA = {
    "type": "object",
    "properties": {
        "thought": {"type": "string"},
        # No minItems/maxItems here on purpose: some strict-schema backends reject those keywords
        # and some enforce them, which would make the press cap bind differently per seat. The
        # runner enforces the cap itself, so every seat gets the same outcome.
        "actions": {"type": "array", "items": {"type": "string", "enum": sorted(RVB_BUTTONS)}},
        "key_moment": {"type": "string"},
        "notes": {"type": "string"},
    },
    "required": ["thought", "actions"],
}



def _sha16(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()[:16]


def rvb_system(goal: str = "game") -> str:
    return RVB_SYSTEM_TEMPLATE.replace("__GOAL__", RVB_GOALS[goal])


# Provenance namespace for RVB prompts: rvb1, rvb2, ... (TAB stays vNN). The site admits per category.
# RVB_SYSTEM / RVB_PROMPT_* name the rvb1 prompt, the one calibration run 1 played.
RVB_SYSTEM = rvb_system("game")
RVB_PROMPT_VERSION = RVB_GOAL_VERSIONS["game"]
RVB_PROMPT_SHA = _sha16(RVB_SYSTEM)


@dataclass(frozen=True)
class Category:
    id: str
    prompt_version: str
    prompt_sha: str
    system: str          # with the __IDENTITY__ placeholder
    allowed: frozenset
    schema: dict

    def render_system(self, identity: str) -> str:
        return self.system.replace("__IDENTITY__", identity)


def rvb_category(goal: str = "game") -> Category:
    system = rvb_system(goal)
    return Category(RVB, RVB_GOAL_VERSIONS[goal], _sha16(system), system, RVB_ALLOWED, RVB_SCHEMA)


CATEGORIES = {
    TAB: Category(TAB, TAB_PROMPT_VERSION, TAB_PROMPT_SHA, TAB_SYSTEM, frozenset(TAB_ALLOWED), TAB_SCHEMA),
    RVB: rvb_category("game"),
}


def rvb_history_entry(turn: int, thought: str, actions: list) -> str:
    """One line of the model's own past: what it said and what it pressed. Nothing observed by the harness."""
    pressed = " ".join(actions) if actions else "nothing"
    return f"turn {turn}: {thought} -> pressed [{pressed}]"


def rvb_user_message(notes: str, recent: list, clock: tuple | None = None) -> str:
    """clock=(turn, budget) is the rvb2 speedrun timer; rvb1 passes nothing and reads as before."""
    head = f"TURN {clock[0]} OF {clock[1]}.\n\n" if clock else ""
    return (f"{head}YOUR NOTES:\n{notes or '(no notes yet)'}\n\n"
            f"YOUR RECENT TURNS (what you thought and what you pressed):\n{chr(10).join(recent) or '(none yet)'}"
            "\n\nThe screenshot is attached. Take your turn.")
