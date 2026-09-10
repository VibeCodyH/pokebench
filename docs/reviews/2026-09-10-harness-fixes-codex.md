Implemented without committing. `PROMPT_VERSION` is **v18** because model-visible wording changed.

- **A — `serve_live.py:_menu_open`, `_a_until_dialog_end`:** Single-frame A presses, settled boundary checks before every press, truthful stop reasons, and per-press traces. Verified against [pokered menu layouts](https://github.com/pret/pokered/blob/master/data/text_boxes.asm), RAM fixtures, and a temporary emulator run covering naming, starter Yes/No, FIGHT, and move selection.
- **B — `qwen_red.py:build_map`:** D/S now requires underlying collision walkability. Tests cover blocked and enterable gate coordinates. Historical gate windows cannot be reconstructed because the audited run omitted raw collision.
- **C — `serve_live.py:get_frame`, `_settle_screen`, `_screen_text`; both runner loops:** Bounded passive settling, snapshot flags, text decoding gated by actual UI, and map suppression for dialogue—including empty text—or unsettled frames. Temporary emulator replay verified the lab escort, starter sequence, naming grid, and Pokédex preview.
- **D — `qwen_red.py:compact`; both runner loops:** Initializing party slots remain visible; return trips say “back at the starting position”; full helper transcripts are retained, with explicit omission counts in shortened history quotes. Verified with unit tests, the temporary starter slot, and turn 418’s exact recorded steps.
- **E — `run_benchmark.py:run`, `main`:** Exact provider PNGs saved under `frames/turn-0001.png`; added `--no-frames`, raw collision/warps, party count, and snapshot flags. Tests verify byte equality, retry preservation, and disabled saving. README documents the changed fields.

**Validation:** requested compilation passed; `python3 -m unittest` passed **16 tests**; diff checks passed.

Not verified: live HTTP/ticker integration or exact historical replacement-switch and gate states. Flood-fill finding 1, scoring, milestones, history policy, and the six-action contract remain unchanged as instructed. No coaching was added; no borderline coaching changes remain.
