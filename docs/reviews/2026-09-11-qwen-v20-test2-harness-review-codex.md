**This is predominantly a MODEL failure, but “the harness never misled it, so nothing needs changing” is too strong.** The introduction’s location text supplied a false premise that Qwen later used in its corruption theory. There are also accounting defects.

I audited **737 records, 734 completed turns, and 2,241 action steps**, without editing files.

1. **HARNESS — The introduction is falsely located in Red’s House 2F, and the model explicitly builds on that claim.**

   Turn **1** receives `map: Pallet Town (0,0)` during the Game Freak introduction. Its feedback then says:

   > `MAP CHANGED Pallet Town -> Red's House 2F`

   Turns **2–6** receive `Red's House 2F (3,6)` during Oak’s introductory speech and name selection. These are initialized map coordinates, not the scene being displayed. The game prepares its destination before presenting the introduction. [Pokémon Red introduction source](https://raw.githubusercontent.com/pret/pokered/master/engine/movie/oak_speech/oak_speech.asm).

   The model adopts this immediately: turn **2 NOTES** says “In Red’s House 2F, intro dialogue with professor ongoing.” Later:

   - **190:** “Intro … fired in Red’s House 2F, not lab -> Oak flag never set.”
   - **195:** explicitly cites **turn 2** as evidence of the broken save.
   - **705, 708–711:** claims the speech happened in the wrong room and disabled the starter event.

   This establishes contamination of its reasoning, **not proof that correcting the header would have prevented failure**. Qwen invents the causal connection between the introduction and starter acquisition.

   **Minimal fix:** establish whether overworld location is meaningful during startup; suppress or qualify initialized map/position fields in both STATE and history until then. Preserve the actual introduction and naming text. Relevant paths: [compact()](/path/to/pokebench/qwen_red.py:124), [feedback construction](/path/to/pokebench/run_benchmark.py:457), [/frame](/path/to/pokebench/serve_live.py:537).

   This is distinct from the previously fixed alphabet dump and hidden-dialogue navigation defects.

2. **MODEL — The northern road was visible and correctly walkable; Qwen abandoned it without reaching the trigger.**

   One correction to the owner’s chronology: **turn 24 enters Oak’s Lab**; turn 25 begins inside. Leaving home is correctly credited at **21**.

   Another correction: Oak’s interception checks **Pallet y=1**, rather than requiring arrival at y=0. No post-introduction step reaches either row. Blue’s “Gramps isn’t around” is the expected pre-escort dialogue. [Pallet trigger](https://raw.githubusercontent.com/pret/pokered/master/scripts/PalletTown.asm), [lab dialogue conditions](https://raw.githubusercontent.com/pret/pokered/master/scripts/OaksLab.asm).

   I reconstructed every displayed map from its recorded collision grid, warps and position: **676/676 exact matches**. The following covers **every Pallet observation with y≤6**, grouping identical positions. Bounds are inclusive.

   | Turns | Position | Window x; y | Road `(10..11,0..1)` |
   |---|---|---|---|
   | 1 | 0,0 | −4..5; −4..4 | Outside; startup map hidden |
   | 22, 260 | 5,6 | 1..10; 2..10 | Outside |
   | 261 | 9,6 | 5..14; 2..10 | Outside |
   | 262, 285, 287, 563, 597, 608, 610, 621, 628 | 13,6 | 9..18; 2..10 | Outside |
   | 289 | 14,6 | 10..19; 2..10 | Outside |
   | 536 | 18,4 | 14..23; 0..8 | Outside |
   | 539, 552 | 16,5 | 12..21; 1..9 | Outside |
   | 540–541 | 16,2 | 12..21; −2..6 | Outside |
   | 542–548 | 18,2 | 14..23; −2..6 | Outside |
   | **549–550** | **14,2** | **10..19; −2..6** | **All four inside, all `.`** |
   | 551 | 17,5 | 13..22; 1..9 | Outside |
   | 553 | 16,4 | 12..21; 0..8 | Outside |
   | 564, 598–601, 622 | 12,6 | 8..17; 2..10 | Outside |
   | 565 | 11,6 | 7..16; 2..10 | Outside |
   | **566** | **10,5** | **6..15; 1..9** | **Both y=1 tiles inside, both `.`** |

   Turns **549–550** receive this identical grid; the four road tiles are **A3, B3, A4, B4**:

   ```text
      A B C D E F G H I J
    1 . . # . . . . . # .
    2 . . # . . . . . # .
    3 . . # . . . . . # .
    4 . . # # # # # # # #
    5 . . . . @ . . . . #
    6 . . # # # # . . . #
    7 . . # # # # . . . #
    8 . # # D # # . . . #
    9 . . . . . . . . . #
   ```

   At **549**, Qwen chooses four blocked downward walks toward the lab. At **550**, it calls the actual **D8** marker “H8” and walks right. At **566**, it again turns away from the northern approach and enters Blue’s House.

   **Minimal fix:** none. No exit hint, pathing help or stuck intervention is justified.

3. **HARNESS — SIGINT makes `turns_used` one too high and leaves completion status implicit.**

   Both log and console contain exactly **turns 1–734**, with no gaps among completed plans. There is no executed turn 735.

   The loop increments `turn` **before** fetching the observation/calling the model, then passes that counter directly to the final summary. [Increment](/path/to/pokebench/run_benchmark.py:295), [finally block](/path/to/pokebench/run_benchmark.py:490).

   Consequently:

   | Summary field | Audit |
   |---|---|
   | `turns_used: 735` | **Incorrect: 734 completed emulator turns** |
   | `tokens_in: 13407850` | Exactly matches completed-record sum |
   | `tokens_out: 133226` | Exactly matches completed-record sum |
   | `left_house: 21` | Correct: traced **37→0**, ending at Pallet `(5,6)` |
   | Furthest index 0 | Correct |
   | Blackouts `[]` | Correct; no battle, money loss or blackout |
   | Final NOTES | Matches final completed plan and `notes.md` |

   No other rung was legitimately reached: party count is zero throughout, no Route 1 or later map appears, and Pokédex/parcel/badge observations remain unchanged.

   **Minimal fix:** track completed/issued emulator turns separately from the pending attempt number; record `termination_reason: interrupted` and incomplete status. Nothing supports inventing a turn-735 result.

4. **HARNESS — Retry usage is omitted, although duplicates do not inflate turns, history or recorded tokens.**

   Duplicate numbers **116, 229, 351** each consist of:

   - One `model_error` record: invalid JSON plan, `raw_output: ""`, `turn_not_counted: true`.
   - One successful retry under the same turn number.

   Console explicitly records the **five-second retry** for each. These are **empty-response retries**, not double writes of successful plans. Failed attempts never reach `/action/traced`, append history, update NOTES or add tokens.

   However, [OllamaProvider.chat()](/path/to/pokebench/providers.py:132) parses the plan before returning usage. A parse failure discards any usage and timing present in the Ollama response. Thus the totals describe **accepted responses**, not necessarily all inference work. There is no evidence of double-counting; unrecorded retry consumption is the concern.

   A smaller provenance defect: summary reports **`max_output_tokens: null`**, although this adapter sends **`num_predict: 8192`**.

   **Minimal fix:** retain usage/timing independently of plan parsing, including failed attempts; expose the actual output ceiling in summary metadata.

5. **MODEL — The large prompts are explained by retained history, not duplicate records.**

   This runner keeps history from the second-newest milestone. With only one milestone, its anchor remains zero. **No history entries are dropped in this run.** Turn 734 receives **733 history entries**, not approximately 12. [History policy](/path/to/pokebench/run_benchmark.py:200), [assembly](/path/to/pokebench/run_benchmark.py:332).

   Input-token growth, with bars scaled to approximately 1,600 tokens:

   ```text
   Turn   Input tokens
      1     1,325  █
    100     6,407  ████
    300    15,962  ██████████
    500    23,712  ███████████████
    700    31,667  ████████████████████
   ```

   The corresponding system/user text grows from approximately **3.8k to 83.1k characters**. Maximum reported input is **35,676 tokens at 657**, comfortably below 65,536. The accepted-response average is **18,266.8 input tokens**. These figures are consistent with growing history plus the image.

   Timing also needs a distinction:

   - **Total run wall time:** 30,433.1 seconds.
   - **Sum of recorded `model_s`:** **29,031.9 seconds**.
   - Mean model call: **39.55 seconds**; median **36.87**.
   - Largest calls: **657: 187.56s; 325: 157.22s; 438: 151.21s; 474: 145.94s**.
   - Seventeen accepted calls exceed 100 seconds; none reaches the 600-second timeout.

   Turn 117 is slow immediately after a retry, but reloads cannot be established without Ollama timing fields. The roughly **1,401-second remainder** includes emulator work, request overhead, failed requests, saves and interruption handling.

   **Minimal fix:** none to history policy. Preserve provider timing metrics to explain latency.

6. **UNSURE — Some displayed `.` tiles reject movement; most are demonstrably ordinary sprite collisions.**

   Across the run:

   - **Zero `#` observations** correspond to a tile successfully entered as ordinary same-map floor, either earlier or later.
   - **Zero ordinary movement onto displayed `#`.**
   - **25 movements into displayed `#` are valid exit-mat warps**, explicitly covered by v20.
   - **Zero failed advertised D/S approaches** in comparable, visible-map attempts.
   - **67 blocked attempts onto displayed `.`**, across 35 turns.

   Of those 67, **53 target lab `(4,3)`**, Blue’s stationary position. The dialogue and game object definition corroborate that occupancy. [Lab objects](https://raw.githubusercontent.com/pret/pokered/master/data/maps/objects/OaksLab.asm).

   All 35 affected turns are:

   **52, 54, 58, 83, 89, 92, 94, 116, 125, 179, 181, 209, 227, 236, 244, 248, 300, 303, 322, 347–348, 398, 400–401, 408, 445, 472, 486, 491, 529, 638, 641, 645–646, 701.**

   Qwen does overinterpret the terrain grid: at **58** and **400**, it treats `.` as evidence Blue moved. That is not evidence of broken terrain classification. The remaining **14 attempts** involve other plausible NPC positions; the supplied receipts cannot settle every occupancy at execution time.

   **Minimal fix:** no demonstrated terrain fix. For unresolved cases, log visible blocking sprites at the observation and action boundary. The previous flood-fill and warp-overlay defects did **not** recur.

7. **MODEL — Dialogue handling, action execution and NOTES do not substantiate the soft-lock theory.**

   **First conversation:** turns **30–32** press A at lab `(4,5)` with no dialogue opening. At **33**, Qwen moves to `(4,4)` and starts Blue’s dialogue. At **34**, the helper performs two A presses:

   ```text
   before: ui=true
   press 1: “RED! Gramps / isn't around!”, dialogue still open
   press 2: ui=false, stop_reason=closed
   ```

   Turn **35** correctly recognizes that Blue said Oak was absent, then insists Oak must nevertheless be elsewhere inside.

   Across **115 helper calls**, I found no demonstrated premature stop or overshoot. The helper stops at the two naming menus and, at **426**, performs zero presses because a menu is already open. Its **38 zero-press, no-dialogue calls** are correct no-ops, frequently after Qwen talks toward empty space.

   Map suppression is also consistent:

   | Check | Count |
   |---|---:|
   | Text-hidden maps | 57 |
   | Hidden with no dialogue, menu or battle | **0** |
   | Empty snapshot text with `dialog_open=true` | **0** |
   | Empty snapshot text but first action starts with `ui=true` | **0** |

   Four hidden maps have a menu but no dialogue box: **196, 341, 676, 700**. Ten *internal helper samples* briefly have an empty open text box; none becomes a misleading next-turn observation.

   Execution checks:

   - **18 overlong plans lose 37 trailing actions** under the advertised six-action cap: **96, 141, 146, 166, 188, 192, 230, 238, 336, 342, 346, 354, 471, 485, 511, 516, 629, 669**.
   - All **2,241 executed actions match the first six requested actions**. No invalid strings, fallback substitutions or action errors occur.
   - Seven directional inputs occur with UI open: **3, 5, 72, 304, 342, 488**. Two are intended naming-menu inputs; the other five are model-issued walks during existing or newly opened dialogue.
   - No unexplained movement drift, frame-to-action position mismatch, step discontinuity or final-step/state-after mismatch occurs.
   - Return-to-start feedback is accurate at **117, 146, 474, 511**.
   - `wait_60` dispatches 60 passive emulator frames; ordinary settling and the advertised live ticker can advance additional time. No substitute button action is evident.

   **NOTES are model-authored, but not literally always verbatim:** [the runner truncates them at 600 characters](/path/to/pokebench/run_benchmark.py:453). This happens at **460: 626→600**, and **550: 617→600**. Otherwise it replaces or retains the model’s notes; it does not merge, rewrite or add assertions.

   Belief chronology:

   | First occurrence | Turn |
   |---|---:|
   | `softlock` in thinking | **157** |
   | “Oak flag never set” in output | **187** |
   | `softlocked` in output/NOTES | **188** |
   | Affirmative “starter … flag is set” | **198** |

   Before 157, turns **155–156** show an ordinary lab re-entry and exit-mat movement, with empty screen text. Before 198, turns **195–197** show a Start-menu check, cancellation and waiting. Nothing asserts a starter-event flag.

   The harness does contain the generic **`flags:` label from turn 1**, always reporting Pokédex false, parcel not picked up, seen/owned zero. It supplies no Oak/starter flag, event-completion claim or soft-lock diagnosis. Lab maps and warps identify terrain and exits, not Oak’s presence. The false starter-state belief and its persistence in NOTES are **MODEL**.

   **Minimal fix:** none beyond the startup-location correction in finding 1.

The phase breakdown below attributes the model’s repeated strategy choices; it does not claim every exploratory turn was inherently wasted.

| Turns | Label | Phase and evidence |
|---|---|---|
| 1–6 | HARNESS | Normal introduction/naming; misleading location headers contaminate its later explanation. |
| 7–24 | MODEL | House navigation; exit-mat confusion at 16–20, successful exit 21, lab entry 24. |
| 25–133 | MODEL | Repeated lab searches, Blue conversations and sign interactions; brief exit/re-entry at 48–50 and 99–101. |
| 134–155 | MODEL | Western/southern Pallet search, then returns to lab; never reaches northern road. |
| 156–239 | MODEL | More lab searches, first soft-lock theory, waits 197–208, renewed exploration. |
| 240–296 | MODEL | Searches for a parcel at Mom’s house; exit-mat oscillations at 250–258 and 263–283 in Blue’s House. |
| 297–365 | MODEL | Repeated lab/NPC searches; lab mat oscillation at 329–332. |
| 366–397 | MODEL | **32 consecutive wait-only turns**, then resumes at 398. |
| 398–532 | MODEL | Repeated lab/town returns, desk searches and mislocated entrances; individual sprite collisions remain bounded by finding 6. |
| 533–550 | MODEL | NE tree-line search; correctly rendered road visible at 549–550, then abandoned. |
| 551–632 | MODEL | Repeated Blue’s House entries and exit-mat oscillations: 554–561, 567–595, 602–606, 611–619, 623–626. |
| 633–658 | MODEL | Another lab sweep and re-entry, retaining corruption theory. |
| 659–686 | MODEL | Waiting interrupted by genuine movement, menu checks and town searches. |
| 687–706 | MODEL | Waits, attempted menu/reset investigation, lab re-entry and further movement. |
| 707–734 | MODEL | Final **28 consecutive wait-only turns**. |

For completeness, these are **all maximal episodes of three or more turns with no positional movement in any traced step**, excluding the normal naming sequence at 2–6. They overlap the phases above.

| Turns | Label | Evidence |
|---|---|---|
| 30–32 | MODEL | A at `(4,5)` opens nothing; moving closer works at 33. |
| 53–59 | MODEL | Repeatedly talks to/waits for stationary Blue. |
| 93–95 | UNSURE | Aide dialogue advances correctly; individual NPC-blocked movements cannot all be resolved visually. |
| 119–121 | MODEL | Repeats Poké Ball descriptive text, expecting starter selection. |
| 195–208 | MODEL | Menu investigation followed by first abandonment/idle sequence. |
| 299–302 | MODEL | Empty interaction, ball text, then Blue; keeps misidentifying the target. |
| 366–398 | MODEL | 32 idle turns followed by another blocked approach to Blue. |
| 426–428 | MODEL | Menu probe, then declares soft-lock and waits. |
| 459–463 | MODEL | Calls `(11,11)` the lab entrance; actual door is `(12,11)`. |
| 505–510 | MODEL | Repeats that wrong entrance and invents a blocking Blue. |
| 542–547 | MODEL | Pushes into correctly displayed NE tree barriers. |
| 598–600 | MODEL | Calls `(12,5)` a door; actual Blue’s House entrance is `(13,5)`. |
| 659–668 | MODEL | Waits and dialogue/no-op helper calls under its corruption theory. |
| 670–673 | MODEL | Wait-only abandonment, reversed at 674. |
| 687–700 | MODEL | Twelve idle turns followed by menu/reset checks. |
| 707–734 | MODEL | Final uninterrupted idle sequence. |

**Wait totals:** **163 `wait_60` actions across 128 turns; 105 turns contain only waits.** The first explicit decision to stop trying is **197**, but it repeatedly reverses that decision. The last non-wait action is at **706**. There is no 125-turn uninterrupted idle stretch beginning around 600.

The remaining receipt limitations are narrow:

| Unresolved question | Minimal missing evidence |
|---|---|
| Whether photographed sprites support Qwen’s visual claims | The referenced input PNGs; already saved by the harness, but absent from this sync |
| Remaining ordinary-floor collisions | Blocking sprite positions at observation/action time |
| Actual Oak/starter script state | Raw relevant event bits and script-state bytes, **audit-only** |
| Empty-response usage and slow-call cause | Ollama usage, `load_duration`, evaluation durations and elapsed time for every attempt |
| Exact failed-attempt input | Error records’ pose/state, screen text and rendered map |
| Exact SIGINT stage | Attempt-stage/termination record and completed-turn counter |

**Verdict:** **(a)** Yes—correct startup location reporting and partial-run accounting before treating the next attempt as a clean benchmark. Preserve failed-attempt usage and output-ceiling metadata. The evidence does not justify navigation aids or changes to NOTES/history strategy.

**(b)** Record this as an **abandoned/interrupted test**, with observed progress **left_house at turn 21, 734 completed turns**. The locked specification ends runs at **1,000 turns or Brock**, not a model’s surrender declaration; this run itself demonstrates that surrender can reverse. Its `think=low` setting also differs from the specification’s Qwen `high` requirement. The partial milestone is valid evidence, but this is not a completed comparable benchmark result. [Locked rules](/path/to/pokebench/BENCHMARK-SPEC.md:10).