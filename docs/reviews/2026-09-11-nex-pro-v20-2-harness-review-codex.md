**The parcel failure is predominantly MODEL behavior. Two additional harness issues are demonstrated: silent action filtering and false Pokédex ownership during the starter preview. This is an abandoned/interrupted run, not a completed benchmark result.**

Audited **720 records, 672 completed turns and 1,698 action steps**. No files edited. Code references below use the initial HEAD, **`0c4a99f`**; the checkout advanced to v21 during the audit.

1. **MODEL — The parcel hunt repeatedly revisits the Mart and eventually invents a prerequisite in Pallet.**

   The four milestones match the owner’s chronology. After reaching Viridian at **274**, another **398 completed turns** produce no parcel. Those observations comprise **366 Viridian City, 18 Pokémon Center and 14 Route 1 turns**.

   It reaches the Mart vicinity at the end of **313**, then spends **314–653** there. During **318–653**, **321 of 336 observations** start on just three tiles: `(29,20)`, `(28,20)` and `(27,19)`.

   **It never enters the Mart and never talks to its clerk.** No traced pose has Mart map ID **42**. Its conversations outside concern Caterpie and Weedle.

   The wrong quest belief starts much earlier than the final NOTES:

   - **18 NOTES:** “continue to Oak’s Lab for the parcel and starter.”
   - Immediately beforehand, **16–17** show empty screen text and unsuccessful staircase navigation. No game dialogue supplied that objective.
   - **169–174**, then **195–219:** repeatedly expects Oak to hand over the parcel despite receiving ordinary Pokémon advice.
   - **653:** waits six times for the NPC outside the Mart.
   - **654:** asserts “Oak’s Parcel must be obtained in Pallet Town first” and heads south.
   - **658:** actually returns to Route 1; **672** still issues movement toward Pallet.

   **Zero harness-generated feedback lines mention “parcel.”** The persistent quest assertions originate in the model’s output. Its false `key_moment` at **480**, “Oak’s Parcel obtained,” does not receive milestone credit.

   **Minimal fix:** none. No coaching or quest hints.

2. **UNSURE — Door obstruction is supported; a broken terrain map is not.**

   I reconstructed **583/583 displayed grids exactly** from collision, warps and observation position, including **359 Viridian grids**.

   The recorded Mart warp is consistently **`[29,19,42]`**. At turn **643**, player `(29,20)`, its grid is:

   ```text
      A B C D E F G H I J
    1 . . . # # # # . . .
    2 . . . # # # # . . .
    3 . . . # # # # . . .
    4 . . . # D # # . . .
    5 . . . . @ . . . . .
    6 . . . . . . . . . .
    7 # . . . . . . . . .
    8 # . . . . . . . . .
    9 # . . . . . . . . .
   ```

   The observed four-turn repetition is real, with this correction: **642 starts west of the building; 643 starts below the door.**

   | Turn | Door shown at | Execution |
   |---|---|---|
   | 642 | G5 | Goes down/right/right/up; ends `(29,20)`, final up blocked |
   | 643 | E4 | Up blocked at `(29,20)` |
   | 644 | E4 | Misreads it as D4; left/up ends `(28,20)`, against `#` |
   | 645 | F4 | Four upward walks into `#`; remains `(28,20)` |

   **The `D` marker remains on the door tile.** Across the run, **181 comparable approaches across 177 turns** fail to enter that tile. Feedback truthfully reports blocked walks; it does not claim the door is locked or requires a parcel.

   At **321–323**, and repeatedly afterward, talking upward from `(29,20)` produces the caterpillar conversation. The game defines a wandering youngster with that dialogue separately from the old man, and its actual Mart entrance is `(29,19)`. This supports ordinary NPC obstruction, not the model’s “gatekeeper” theory. [Viridian objects](https://raw.githubusercontent.com/pret/pokered/master/data/maps/objects/ViridianCity.asm), [dialogue scripts](https://raw.githubusercontent.com/pret/pokered/master/scripts/ViridianCity.asm).

   Terrain checks, excluding startup interpretation:

   | Check | Result |
   |---|---:|
   | Ordinary same-map movement onto displayed `#` | **0** |
   | Displayed `#` at a world tile demonstrably entered as ordinary floor elsewhere | **0** |
   | Movement into `#` causing an exit-mat warp | **19**, correctly documented by v20 |
   | Blocked approaches onto displayed `.` | **13 across 11 turns** |
   | Blocked approaches onto `S` | **0** |
   | Blocked ledge approaches | **6**, all upward into a one-way ledge at **256** |

   The 13 ordinary-floor blocks occur at **39, 45, 91, 114–115, 119, 149–150, 162, 194, 315**. Eight target Blue/Daisy/Oak positions corroborated by interactions; five lack sufficient occupancy evidence.

   This is the same terrain-versus-sprite distinction as **Qwen finding 6**. An NPC occupying a door is game behavior. Missing sprites prevent proving the cause of **every** blocked approach, especially the exact occupancy at 636–650.

   **Minimal fix:** no demonstrated map-rendering change. Record blocking sprite positions at observation/action boundaries, audit-only.

3. **HARNESS — Silent filtering changes the model’s attempted escape sequence.**

   This is the concrete new execution discrepancy:

   | Turn | Requested but removed | Consequence |
   |---|---|---|
   | 267 | `press_down` | Executes five remaining actions; reaches the move list |
   | 268 | `press_down`, `press_right` | Executes `press_b wait_60 press_a`; reopens Fight instead of selecting Run |

   The **MODEL supplied unsupported action names**. The **HARNESS silently executed the remaining sequence**, including its final confirmation button. The schema permits arbitrary strings; filtering occurs afterward. Evidence: `qwen_red.py:45–54`, `run_benchmark.py:388–390`.

   Otherwise:

   - All **1,698 steps match the filtered, capped commands**.
   - **130** requests eight actions and loses two trailing actions; **311** requests seven and loses one. This follows the advertised cap.
   - No fallback substitution or action error occurs.
   - No unexplained positional drift, observation/action position mismatch or final-step/state-after position mismatch occurs.
   - The five two-tile movements are downward ledge hops.
   - **21 directional actions** occur with UI open: two naming inputs, and 19 during dialogue/battle/menu states across **175, 226, 236, 248, 266, 478, 669**. These are requested inputs meeting an open UI, not omitted commands.

   **Minimal fix:** constrain schema items to the existing allowed actions and reject invalid sequences explicitly rather than silently retaining later confirmations. Record rejected actions. Preserve the existing budget and six-action contract.

4. **HARNESS — All 48 failed attempts lose usage and timing; the 47 “refusals” cannot be classified retrospectively.**

   This confirms the sibling accounting defect on the OpenRouter path:

   - **48 failures across 40 turn numbers**, followed by successful retries under those same numbers.
   - **47** generic “refused or could not finish” errors.
   - **1**, at **57**, reports `Expecting value: line 133 column 1 (char 726)`.
   - Every failed record has **`raw_output: null`**, empty `error_body`, and no usage or elapsed time.

   The refusal branch conflates `message.refusal` with finish reasons **`length`, `content_filter`, and `error`**, then discards the response. **None of those 47 can be identified as an actual refusal or a length cutoff from these receipts.** Empty content alone would take a different parsing path. The turn-57 message points to response-envelope JSON decoding; `_plan()` wraps malformed plan JSON in a different error. Evidence: `providers.py:109–112, 244–250`.

   Quantification:

   | Measurement | Amount |
   |---|---:|
   | Recorded accepted input | **7,140,616 tokens** |
   | Recorded accepted completion | **681,481 tokens** |
   | Failed attempts with unrecorded usage | **48** |
   | Actual missing token total | **Unknown** |
   | Explicit retry backoff | **300 seconds** |
   | Recorded successful model-call time | **17,629.7 seconds** |
   | Total wall time | **27,246.8 seconds** |

   The **9,617.1-second remainder** includes failed calls, backoff, emulator/network/save work and interruption overhead; it cannot be assigned entirely to retries.

   **Conditional estimate only:** if all 47 generic errors were 8,192-token length cutoffs, they would represent **385,024 omitted completion tokens**. Reusing each successful retry’s prompt count estimates **370,666 additional input tokens** across the 48 failures. Neither is measured failed-attempt usage.

   `message.reasoning` **was populated on all 672 accepted responses**, yielding 2,203,896 logged characters. Code sends `reasoning_effort: low` and strict JSON schema; receipts do not establish whether the backend honored that effort setting.

   **The sibling’s null output-ceiling defect is absent here:** summary correctly reports **8,192**, matching `max_completion_tokens`. Recorded cost remains **$0 at this free model’s configured rates**; inference usage is still missing.

   **Minimal fix:** preserve finish reason, refusal, usage and elapsed time before validating/parsing the plan; retain response-decoding diagnostics.

5. **HARNESS — Startup location misinformation is present and enters the model’s NOTES.**

   The sibling defect occurs here at:

   - **1–5:** initialized Pallet coordinates during opening/title/menu screens.
   - **2–4:** spurious terrain grids also appear.
   - **5 feedback:** falsely presents `Pallet Town -> Red’s House 2F` as a world transition.
   - **6–9:** intro/name selection located in Red’s House 2F.

   At **6**, NOTES already says it is upstairs “talking to Oak.” After the introduction, **10–13** waits for an imagined upstairs Oak to leave.

   **Minimal fix:** qualify/suppress uninitialized world location and terrain in both observations and feedback. This is the known sibling defect, not a new staircase defect.

6. **HARNESS — Starter-preview bookkeeping is falsely reported as four Pokémon owned.**

   **144–145 STATE** says **`seen 0 owned 4`**, with no party. The same false ownership appears in **143–144 state_after**, then returns to zero after **145**.

   This has a precise explanation: the game temporarily marks the three starters **and Ivysaur** owned so their complete preview entries can display, then clears those bits. [StarterDex source](https://github.com/pret/pokered/blob/master/engine/events/starter_dex.asm).

   The reader forwards those temporary bits as real collection progress through `compact()` (`qwen_red.py:131–134`). No resulting model mistake is established.

   **Minimal fix:** qualify or suppress the ownership count while the starter-preview override is active; retain raw bits for auditing. This is additional to the sibling’s three defects.

7. **HARNESS — Partial-run accounting is wrong by one; milestone accounting is correct.**

   Completed records and console turns are continuously **1–672**. Summary reports **673**, with no termination reason, confirming the sibling SIGINT defect.

   | Milestone | Verified evidence |
   |---|---|
   | Left house, **29** | Traced map **37→0**, ending Pallet `(5,6)` |
   | Starter, **146** | “RED received a CHARMANDER”; state_after retains an initializing party slot; turn 147 observes party count 1 |
   | Route 1, **226** | First action crosses **0→12** |
   | Viridian, **274** | Action crosses **12→1**, ending `(21,35)` |

   There is **no milestone off-by-one**. Full starter initialization at 147 does not invalidate count-based credit at 146.

   **No blackout is evidenced.** Money initializes to 3,000 at 5, rises to **3,175** after winning against Blue at **192**, then never falls. Map transitions show no defeat return. Center healing at **294** restores Charmander from **8/23 to 23/23**.

   **Minimal fix:** completed-turn counter plus explicit interrupted/incomplete termination metadata.

8. **UNSURE — No battle-reader or dialogue-helper regression is demonstrated; some transition details remain unobservable.**

   The owner’s Rattata timing and HP recollection need correction: **293–300 are Center/healing/navigation turns**. The low-HP Rattata battle is **267–271**, at **8/23**, not 8/24.

   After the filtering issue above, **269** uses Scratch, **270** observes Rattata at zero HP, and **271** finishes the reward dialogue. Inputs reached the emulator and advanced the fight.

   Across **47 battle observations**:

   - Enemy species/level match available screen text.
   - **Zero HUD-versus-STATE HP contradictions** and zero `in_battle` flag disagreements.
   - **Zero “not sent out yet” observations.** The trainer introduction occurs inside helper **176**, whose trace lacks enemy RAM; that particular guard is therefore not directly exercised by a model-facing observation.
   - No demonstrated stale Squirtle carried into a wild encounter.

   Across **98 helper calls / 370 internal A presses**, none continues after a recorded menu boundary:

   - **176, 666:** stop at Fight.
   - **243, 669:** stop at level-up statistics.
   - **293:** stops at HEAL/CANCEL after five presses.
   - **294:** the model explicitly confirms HEAL, then the helper completes healing.
   - The only capped helper, **137**, reports the cap honestly during Oak’s escort; turn 138 receives the lab dialogue.

   The reviewed helper uses single-frame presses (`serve_live.py:201–233`). No unrequested helper move selection is evidenced.

   Map/UI checks:

   | Check | Count |
   |---|---:|
   | Maps hidden for text | **87** |
   | Hidden for text with no dialogue/menu/battle | **0** |
   | Empty screen text with an open dialogue box | **2: 227, 237** |
   | Empty battle transition without a dialogue box | **1: 665** |

   These three snapshots report `settle: cleared`; the model waits and encounter text appears. That shows tilemap stability is not proof of battle readiness, but does **not** establish missing text or eaten inputs. No Mart/shop menu was reached to test.

   **Minimal fix:** no demonstrated helper change. For unresolved timing questions, record battle phase and UI/menu state immediately before ordinary button presses, plus enemy RAM in helper samples.

9. **MODEL — History trimming works; the continuing wrong assertions are model-authored NOTES.**

   The trim takes effect in the **request for 275**, after completing milestone turn 274. Its anchor becomes **226**.

   | Turn | Retained history entries | Input tokens | Completion tokens |
   |---|---:|---:|---:|
   | 1 | 0 | 1,258 | 211 |
   | 100 | 99 | 6,101 | 934 |
   | 274 | 128 | 9,133 | 4,901 |
   | 275 | 49 | 4,087 | 841 |
   | 400 | 174 | 9,953 | 328 |
   | 600 | 374 | 19,036 | 429 |
   | 672 | 446 | 22,316 | 907 |

   No context-cap trimming is needed. **7,140,616 input tokens exactly matches the accepted-record sum**, averaging 10,625.9 per turn. Retry records do not duplicate history.

   NOTES remain verbatim model output throughout: none exceeds 600 characters. Final NOTES matches both the last plan and `notes.md`. All five “back at the starting position” feedback lines are accurate; no dialogue-history omission threshold is reached.

   **Minimal fix:** none to history or NOTES policy.

The phases are:

| Turns | Phase | Attribution |
|---|---|---|
| 1–29 | Introduction and house exit | HARNESS startup misinformation; MODEL staircase confusion |
| 30–136 | Pallet/lab searches before Oak’s escort | MODEL building/NPC/quest misidentification |
| 137–176 | Escort, starter, repeated Blue/Oak interactions | MODEL repetitions; starter obtained at 146 |
| 177–192 | Rival battle | Actual battle progress |
| 193–225 | Repeated Oak conversations, then departure | MODEL parcel/Pokédex expectations |
| 226–274 | Route 1, four wild encounters, Viridian arrival | Actual progress; filtering discrepancy at 267–268 |
| 275–294 | Find Center attendant and heal | MODEL alignment mistakes, then successful healing |
| 295–313 | Re-enter Center three times, then locate Mart vicinity | MODEL building confusion |
| 314–653 | Mart entrance hunt | MODEL spatial/quest repetition; individual obstruction causes partly UNSURE |
| 654–672 | Return south; another Pidgey battle | MODEL wrong destination, still actively playing |

For a reproducible inventory, these are the **stationary unproductive episodes of three or more turns**, requiring no positional movement in any traced step. Normal introduction, acquisition and progressing battle intervals are excluded; movement loops follow the table.

| Turns | Label | Evidence |
|---|---|---|
| 10–13 | MODEL | Waits for imagined Oak upstairs |
| 19–22 | MODEL | Treats `(0,5)` as stairs; waits/retries blocked downward movement |
| 60–62 | MODEL | Repeated A toward supposed aide; no dialogue opens |
| 76–78 | MODEL | Reopens bookshelf text while calling it Oak |
| 83–85 | MODEL | Repeats Poké Ball descriptive text |
| 92–97 | MODEL | Waits/repeats Blue’s “Gramps isn’t around” |
| 117–122 | MODEL | Repeated Daisy approaches/conversation, expecting an item |
| 148–166 | MODEL | Repeats Blue’s ordinary taunt, expecting battle initiation |
| 168–174 | MODEL | Repeats Oak’s wild-Pokémon advice, expecting parcel |
| 195–219 | MODEL | Repeats Oak’s training advice, expecting parcel/Pokédex |
| 287–289 | MODEL | Talks from the wrong counter position |
| 319–340 | MODEL | Repeats door attempts and caterpillar tutorial, expecting clearance |
| 347–350 | UNSURE | Correctly targets `D`; exact sprite occupancy unlogged |
| 352–361 | MODEL | Repeated up into `#` at `(28,19)` |
| 369–371 | MODEL | Repeated right into wall at `(28,19)` |
| 375–377 | MODEL | Repeated up into the same wall |
| 404–406 | UNSURE | Correctly targets `D`; occupancy unlogged |
| 423–426 | UNSURE | Correctly targets `D`; occupancy unlogged |
| 451–453 | MODEL | Mislocates door; walks into `(28,19)` wall |
| 469–472 | MODEL | Same wrong doorway alignment |
| 478–481 | MODEL | Treats caterpillar conversation as an unlocking tutorial |
| 493–495 | MODEL | Claims two clear eastward steps through a wall |
| 501–508 | UNSURE | Repeated correctly aimed door attempts |
| 513–517 | UNSURE | Repeated correctly aimed door attempts |
| 558–563 | UNSURE | Repeated correctly aimed door attempts |
| 571–573 | UNSURE | Repeated correctly aimed door attempts |
| 604–608 | MODEL | Repeated up into `(28,19)` wall |
| 629–631 | UNSURE | Repeated correctly aimed door attempts |

Movement also conceals repetition: **31–37** repeatedly enters Blue’s House; **40–48** repeatedly enters Red’s; **100–109** cycles through the lab entrance; **126–129** repeats Blue’s House; **296–306** repeatedly mistakes the Center for the Mart. The broader **51–72** aide search and **314–653** Mart loop repeatedly move without achieving their stated interaction. These are MODEL strategy episodes; isolated collisions retain the uncertainty described above.

The missing receipts that limit conclusions are narrow:

| Unsettled question | Minimal missing field/artifact |
|---|---|
| Refusal versus length/filter/error; failed consumption | `finish_reason`, `refusal`, `usage`, per-attempt elapsed time |
| Turn-57 decoding failure | Response status and undecodable response body |
| Exact failed-attempt input | Observation reference containing state, text and rendered map |
| NPC occupancy at each blocked action | Sprite positions at observation and action boundaries |
| Ordinary A landing during an animation/menu transition | Pre-input battle phase/menu state and emulator frame number |
| Internal trainer-intro enemy validity | Enemy RAM in helper trace samples |
| Independent verification of visual claims | Referenced input PNGs, absent from this sync |
| Exact interruption stage | Attempt-stage termination record |

**Verdict:** Beyond the three sibling defects, correct **silent invalid-action filtering** and **starter-preview ownership reporting** before treating another OpenRouter attempt as clean. No demonstrated evidence requires changing navigation maps or battle-helper behavior. The newly committed v21 changes are outside this audit.

Record this run as **abandoned/interrupted, 672 completed turns**, preserving its valid partial achievement: **Viridian City, index 3, turn 274**. It reached neither the **1,000-turn endpoint nor Brock**, so it is not a completed comparable result under [BENCHMARK-SPEC.md](../../BENCHMARK-SPEC.md#L10). The termination was the owner’s SIGINT, not model surrender.