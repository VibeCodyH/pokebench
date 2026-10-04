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
RVB_SYSTEM = """__IDENTITY__ Each turn you get one screenshot of the Game Boy screen. The game keeps running in real time between turns, so the screenshot is a moment in time. Each turn you press up to six buttons, in order, one press each.

Buttons (strings, exactly): up, down, left, right, a, b, start, select.

Overall goal: beat the game.

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

# Provenance namespace for RVB prompts: rvb1, rvb2, ... (TAB stays vNN). The site admits per category.
RVB_PROMPT_VERSION = "rvb1"
RVB_PROMPT_SHA = hashlib.sha256(RVB_SYSTEM.encode()).hexdigest()[:16]


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


CATEGORIES = {
    TAB: Category(TAB, TAB_PROMPT_VERSION, TAB_PROMPT_SHA, TAB_SYSTEM, frozenset(TAB_ALLOWED), TAB_SCHEMA),
    RVB: Category(RVB, RVB_PROMPT_VERSION, RVB_PROMPT_SHA, RVB_SYSTEM, RVB_ALLOWED, RVB_SCHEMA),
}


def rvb_history_entry(turn: int, thought: str, actions: list) -> str:
    """One line of the model's own past: what it said and what it pressed. Nothing observed by the harness."""
    pressed = " ".join(actions) if actions else "nothing"
    return f"turn {turn}: {thought} -> pressed [{pressed}]"


def rvb_user_message(notes: str, recent: list) -> str:
    return (f"YOUR NOTES:\n{notes or '(no notes yet)'}\n\n"
            f"YOUR RECENT TURNS (what you thought and what you pressed):\n{chr(10).join(recent) or '(none yet)'}"
            "\n\nThe screenshot is attached. Take your turn.")
