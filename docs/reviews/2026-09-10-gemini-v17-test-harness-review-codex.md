**I would keep this as a test run.** Brock’s defeat at turn 501 is supported, but `d797b71` alone does not make the harness clean. I audited all 500 records and 2,490 action steps without editing files.

1. **HARNESS — Flood-fill turns traversable floor into apparent walls.**

   [build_map()](../../qwen_red.py#L312) conflates “no connection within this window” with “blocked terrain.” This is especially misleading around Pewter Gym: the door remains visible while its approach becomes `#`.

   Evidence:
   - **292 observations of `#`, across 43 turns and 53 world tiles, describe tiles subsequently entered successfully.** Of these, 284 observations are in Pewter City.
   - Example: Viridian `(20,12)` is `#` at turns **136–137**, becomes `.` after scrolling, and is occupied at **138**.
   - Across consecutive usable maps, **60 overlapping cells change between `#` and `.` in 12 turn pairs**: 50→51, 68→69, 69→70, 72→73, 137→138, 289→290, 323→324, 353→354, 356→357, 357→358, 359→360, 361→362.
   - The 43 turns with `#` later contradicted by actual occupancy are **69, 136–137, 389–391, 394–396, 398–402, 404–409, 411, 413–415, 420, 438, 441, 443, 445, 447, 449, 454–455, 462–468, 472, 490–491**.

   **Minimal fix:** render underlying terrain walkability without flood-fill. This removes a misleading spatial inference; it adds no navigation help.

   **Important distinction:** I found **zero ordinary same-turn movements directly onto a displayed `#`**. The defect appears when comparing world coordinates across windows. Expected exit-mat movements into an edge `#` are separate.

2. **HARNESS — `a_until_dialog_end` sometimes confirms a choice instead of stopping before it.**

   Four definite overshoots:

   | Turn | Evidence |
   |---|---|
   | **76** | Final helper only narrates “Go! SQUIRTLE!” but the next observation is already the **move-selection menu**. It passed FIGHT. |
   | **266** | The helper transcript advances through “Will RED change POKéMON?” into **“Bring out which POKéMON?”** It selected Yes. Turn 267 cancels this unintended selection. |
   | **480** | After declining a switch, the helper advances through Onix’s send-out and leaves the **move menu** open. |
   | **500** | Same overshoot during the Brock rematch. |

   These are internal extra confirmations, despite perfect agreement between top-level `plan.actions` and `steps`.

   [_a_until_dialog_end()](../../serve_live.py#L211) samples menu state around relatively long A holds and waits. **The precise missed detection point is unlogged**, so cursor timing is a plausible mechanism, not a proven one.

   **Minimal fix:** stop on a reliably established choice/menu boundary before another A can register; verify both battle menus and replacement Yes/No prompts. Preserve the existing action contract.

3. **HARNESS — Gate warp markers falsely advertise an enterable tile.**

   The south gate marks **both `(4,0)` and `(5,0)` as `S`**. Northward movement from `(4,1)` repeatedly fails; moving right and then up succeeds. The north gate repeats this with `D`.

   **13 failed advertised-warp movements** occur at:
   - **152:** four.
   - **220–221:** four.
   - **315:** one.
   - **377:** four.

   Successful counterparts are **153, 222, 316, 378**.

   This is **not evidence of an E5 offset**: all 365 grids place `@` at E5, ordinary movement agrees with the coordinate transform, and observed working entrances align with their markers. The problem is that [warp overlays override collision classification](../../qwen_red.py#L351).

   **Minimal fix:** preserve the distinction between a warp-table coordinate and a physically enterable warp tile. Validate the rendering against collision data; do not describe every marker as unconditionally walkable.

   Across **1,625 in-window, same-map movement attempts**, there were **27 advertised-passable/no-movement discrepancies**: these 13 warp attempts and 14 `.` attempts. The latter occur at **8, 46, 154, 171, 223, 262, 332, 347, 392, 422**, often involving NPCs, item objects, or trainer interception. Those are **UNSURE as harness defects**: the background collision grid omits sprites, and the log lacks object/busy-state evidence needed to resolve every instance.

4. **HARNESS — Observation settling still exposes transitions as navigable overworld.**

   - **12→13:** helper returns `closed`, but its settle result is **`capped`**. Position subsequently changes from lab `(5,5)` to `(5,3)`. Turn 13 receives empty screen text and a map; **all six requested walks encounter `ui=true` and accomplish no movement**. The next observation contains Blue’s dialogue.
   - **18→19:** another **`capped`** settle. Turn 19 receives empty screen text and a map; **four walks are consumed by Blue’s dialogue**, then its helper advances it.
   - These are the **only two capped action settles** among 2,490 steps.

   [Frame settling](../../serve_live.py#L553) and [map suppression](../../run_benchmark.py#L303) do not establish the same thing: an empty decoded string does not establish overworld control.

   Counts:
   - **124** “map hidden” observations.
   - **Zero demonstrated cases** where that placeholder hides an otherwise usable, unobstructed overworld observation.
   - **14 empty-text observations have `ui=true` at execution start:** **13, 19, 22, 76, 105, 160, 183, 244, 308, 325, 365, 424, 476, 498**. Eleven are battle observations; 365 is trainer interception. Only 13 and 19 demonstrate the misleading navigation consequence above.
   - Because frame-time UI flags are absent, these 14 cannot all be called “text boxes already open when photographed.”

   Separately, **turn 2** receives an alphabet dump as `SCREEN TEXT` and consequently identifies a naming screen; **turn 3 is actually NEW GAME**. The [text reader’s UI gate](../../serve_live.py#L181) still admits non-dialogue tile data during startup.

   **Minimal fix:** expose and use snapshot-time UI/transition validity, finish settling before presenting a playable observation, and suppress non-text startup tile decoding. No hints or automatic strategic actions are needed.

5. **HARNESS — A few feedback statements and dialogue receipts are misleading or incomplete.**

   - **418:** feedback says **“(no movement)”**, but steps show `(10,16) → (10,17) → (10,16)`. This is a return to the starting position.
   - **89 and 501:** helper transcripts reach the hard **30-entry truncation**. Turn 89’s stored transcript ends during Oak’s speech, while the next screen is already Blue discussing the Town Map. The promise that skipped dialogue is quoted back is incomplete without any truncation notice.
   - **17 and 18’s pre-state:** `party: none` hides the pending starter slot even though turn 17 reports “RED received a SQUIRTLE!” and receives milestone credit. [compact()](../../qwen_red.py#L114) silently drops level-zero slots.

   **Minimal fixes:** say “same ending position”; preserve complete helper transcripts or explicitly mark omissions; represent an initializing party slot as pending rather than “none.”

   I found **no false map-ID transition**, no frame-to-execution position mismatch, and no mismatch between the final step position and `state_after`. Turn 12’s subsequent scripted movement is the exception between consecutive observations described above.

6. **MODEL — There were two blackouts, including one deliberate blackout.**

   | Turn | Proof |
   |---|---|
   | **187** | Money **2175→1087**, Forest→Viridian City, restored party, transcript **“RED blacked out!”** The plan explicitly requests poison steps to faint and respawn. |
   | **487** | Money **1227→613**, Gym→Pewter City, restored party, same explicit blackout transcript. Onix defeats the remaining Rattata. |

   Squirtle also faints at **272** without a blackout because Rattata wins the battle, and at **483** before the eventual turn-487 blackout.

   **Minimal fix:** no gameplay fix. Report the historical run’s two blackouts accurately; the absent field is already explained by the loaded revision.

7. **UNSURE — The receipts cannot settle every visual or internal-helper question.**

   There are no saved screenshots in this run directory. `state` is compact text, and helper `steps` cover whole helper calls, not their internal A presses.

   The minimal additional evidence is:

   | Unresolved question | Minimal field/artifact |
   |---|---|
   | Screenshot versus RAM, visible cursor, stale enemy | **Saved input screenshot**, referenced by `frame_file` |
   | Exact reproduction of `build_map()` | **Raw `collision` and `warps`** |
   | Empty text versus actual UI/transition | Snapshot **`dialog_open`, `menu_open`, battle and settle state** |
   | Starter milestone’s raw predicate | **`party_count`**, including initializing slots |
   | Exactly where a helper crossed a menu | **Per-internal-press UI/menu boundary trace** |

   **Minimal fix:** preserve these observations, without feeding additional analysis or advice to the model.

The **3+ turn stalled/repeated-route episodes** are below. I excluded progressing combat, ordinary multi-stage purchases, and purposeful return journeys for healing. Episode boundaries describe the repeated excursion; they do not imply every individual button press was wasted.

| Turns | Label | Evidence |
|---|---|---|
| **60–63** | **MODEL** | Reverses course and re-enters the already visited Pokémon Center, again calling it the Mart. |
| **165–168** | **MODEL** | Repeated approaches between `(8,30)` and `(12,32)` toward an assumed Antidote; blocked directions agree with the map. |
| **172–182** | **MODEL** | Revisits the southwest clearing and sign, then repeats the same item-approach loop while poisoned. Later thoughts explicitly accept fainting. |
| **225–243** | **MODEL** | Re-explores the same southern dead ends; **234–236** directly oscillate `(2,30) ↔ (7,31)`. No recorded turn 231 is included in the attribution. |
| **247–257** | **MODEL** | Repeats the western dead end and `(8,30)/(12,32)` loop after the Weedle battle; advances east at 258. |
| **327–329** | **MODEL** | Kakuna stays at **6 HP**. The requested cursor inputs select **Tail Whip four times**, as the transcripts explicitly report. |
| **387–392** | **UNSURE** | Initial Gym search moves west/north, reverses, and returns around the Center; erroneous `#` terrain is present in this area. |
| **397–415** | **UNSURE** | Repeated roof/east-fence/south-approach loops. Model route reversals are clear, but false floor-as-wall rendering contaminates attribution. |
| **438–450** | **UNSURE** | Repeated attempts to leave the Gym courtyard, especially `(8,19) ↔ (14,19)`, while seeking healing; same map defect. |
| **462–467** | **UNSURE** | Repeats north/south approaches around the Gym fence before taking the successful route. |

**Harness fixes for the UNSURE rows are the map fixes above. MODEL rows need no harness change.** The shorter gate and lab failures are accounted for separately; they are not three consecutive wasted turns.

The Forest interval **153–381 contains 228 logged decisions**, not 228 turns of being stuck in the forest: **151 start in the Forest, 77 elsewhere**, and **53 start in battle**. Its main components are the southwest loops, deliberate blackout and resupply, catching Rattata, trainer battles, and the **275–316 healing retreat/return**. That retreat follows Squirtle fainting and Rattata surviving at 1 HP; it is purposeful recovery.

The milestone audit is:

| Milestone | Turn | Verification |
|---|---:|---|
| Left house | 10 | Step changes map **37→0**. |
| Starter | 17 | Receipt dialogue supports acquisition, but compact state says `none`; **raw count cannot be independently verified**. Fully initialized party appears after 18. |
| Route 1 | 32 | Step changes map **0→12**. |
| Viridian City | 53 | **12→1**. |
| Parcel | 65 | Parcel appears in bag; receipt dialogue agrees. |
| Pokédex | 90 | Flag first becomes true in `state_after`. |
| Forest | 153 | **50→51**. |
| Pewter City | 381 | **13→2**. |
| Gym | 420 | **2→54**. |
| Brock | 501 | Boulder badge appears; victory and badge dialogue agree. |

There is **no demonstrated off-by-one in those nine independently supported checkpoints**. Pokédex dialogue occurs at 89, but the locked RAM predicate becomes true at 90. I would not move either that credit or starter credit based solely on narration.

Other checks came back clean or bounded:

- **Execution:** all **2,490 steps exactly match `plan.actions`**, in order. No invalid-action filtering, six-action truncation, fallback substitution, execution errors, or unexplained movement direction occurred.
- **Battle reader:** no demonstrated stale species or HP/level contradiction against available screen text and plans. The four `not sent out yet` observations—**22, 424, 476, 498**—are trainer introductions. At **267, 337, 343, 430, 480, 500**, RAM already holds the upcoming replacement during switch selection; these are not previous-battle stale opponents. Pixel-level verification remains unavailable.
- **Helper limits:** turn **89** legitimately reaches the advertised 100-press cap. Also, `closed` plus `ui=true` in battle is not by itself premature termination: the battle menu still makes UI true.
- **Tokens:** logged totals sum exactly to **5,044,673 input / 203,012 output**. Average input is **10,089.346**. The canonical runner retains history from the second-newest milestone, not 12 turns: **turn 381 contains 290 history entries**, approximately **53,533 system/user text characters**, and **21,073 input tokens** including the image. The drop to **4,575 tokens at turn 421** matches the milestone-window reset. This is deliberate prompt growth, with no evidence of double-counting.

**Clean run? No, not with only the retry fix.** Before the first recorded result, fix the false terrain/warp representations, helper menu overshoot, transition/text validity, and the small false or silently truncated feedback cases; preserve the missing visual/raw-state receipts so those fixes can be verified. Keep the scoring rules, history policy, and model mistakes intact. This run remains credible evidence that Gemini beat Brock, but not a clean measurement of the turn count.


