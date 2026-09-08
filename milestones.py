"""PokéBench milestone ladder — objective progress scoring from game state.

Each milestone is auto-detected from the pokemon-agent state dict (map_id / badges / party).
Score for a run = furthest milestone whose predicate was EVER true within the turn budget.
See BENCHMARK-SPEC.md §0-1 for the locked rules.
"""
from __future__ import annotations

RED_HOUSE_MAPS = {37, 38}  # Red's House 1F / 2F


def _map_id(state) -> int:
    return (state.get("map") or {}).get("map_id", -1)


def _party_count(state) -> int:
    return len(state.get("party") or [])


def _boulder_badge(state) -> bool:
    # Boulder = bit 0 of the badge byte; state exposes it as a name list + badge_count.
    p = state.get("player") or {}
    badges = p.get("badges") or (state.get("flags") or {}).get("badges") or []
    return "Boulder" in badges or (p.get("badge_count") or 0) >= 1


# Ordered ladder: (key, label, predicate). Index = progression rank.
MILESTONES = [
    ("left_house",       "Left the house",        lambda s: _map_id(s) not in RED_HOUSE_MAPS and _map_id(s) != -1),
    ("route_1",          "Reached Route 1",       lambda s: _map_id(s) == 12),
    ("got_starter",      "Got a starter",         lambda s: _party_count(s) >= 1),
    ("viridian_city",    "Reached Viridian City", lambda s: _map_id(s) == 1),
    ("viridian_forest",  "Entered Viridian Forest", lambda s: _map_id(s) == 50),
    ("pewter_city",      "Reached Pewter City",   lambda s: _map_id(s) == 2),
    ("pewter_gym",       "Entered Brock's Gym",   lambda s: _map_id(s) == 53),
    ("beat_brock",       "Beat Brock (Boulder Badge)", _boulder_badge),
]


class MilestoneTracker:
    """Records the first turn each milestone fired; reports furthest reached."""

    def __init__(self):
        self.first_turn: dict[str, int] = {}
        self._started = False

    def update(self, state, turn: int) -> None:
        if not self._started:
            # Ignore the pre-game title/boot state (map_id reads 0 = Pallet Town),
            # which would false-fire "left_house". Tracking begins once she's inside
            # Red's House — every new game places Red in his bedroom first.
            if _map_id(state) in RED_HOUSE_MAPS:
                self._started = True
            return
        for key, _label, pred in MILESTONES:
            if key not in self.first_turn:
                try:
                    if pred(state):
                        self.first_turn[key] = turn
                except Exception:
                    pass

    @property
    def furthest_index(self) -> int:
        """Highest ladder index ever reached, or -1 if none."""
        idx = -1
        for i, (key, _l, _p) in enumerate(MILESTONES):
            if key in self.first_turn:
                idx = i
        return idx

    def summary(self) -> dict:
        i = self.furthest_index
        return {
            "milestones": [
                {"key": k, "label": l, "turn": self.first_turn.get(k)}
                for k, l, _p in MILESTONES if k in self.first_turn
            ],
            "furthest_key": MILESTONES[i][0] if i >= 0 else None,
            "furthest_label": MILESTONES[i][1] if i >= 0 else None,
            "furthest_index": i,
            "beat_brock": "beat_brock" in self.first_turn,
        }


if __name__ == "__main__":  # live verify against the running game
    import requests, json
    s = requests.get("http://localhost:8765/state", timeout=15).json()
    print("live map:", (s.get("map") or {}), "party:", _party_count(s), "badges:", (s.get("player") or {}).get("badges"))
    for k, l, p in MILESTONES:
        print(f"  {'HIT ' if p(s) else '    '} {k:16} {l}")
