# Model corpus (planning, 2026-09-08)

Eligibility: **vision-capable models only** (BENCHMARK-SPEC §0). The harness feeds a screenshot every turn; a
text-only model would be playing a different game off the ASCII map and SCREEN TEXT alone.

Every local entry below runs on the Unraid box (RTX 3090, 24 GB). Budget rule of thumb from the Qwen runs:
a 27B dense at Q4_K_M with 64K context sits at ~20.5 GB. Anything larger on disk than ~20 GB needs a shorter
context or MoE. `ctx` is reported per run in summary.json, so a smaller context is allowed but disclosed.

## Tier 1 — frontier (API, phase 2)
Obvious set; every current model in each family, as many versions as we can afford. IDs and prices get verified
against provider docs at adapter-smoke time (`providers.py`, `models.yaml` still carries PLACEHOLDER rows).

| Family | Models to run |
|---|---|
| Anthropic | Fable 5.1, Opus 5, Opus 4.8, Opus 4.6, Sonnet 5, Haiku 4.5 (and older Haiku if still served) |
| OpenAI | GPT-6 line (astra + siblings), GPT-5.5, o-series if still offered |
| Google | Gemini 3.8 Pro / Flash, 3.5 line |
| xAI | Grok 4.5 |
| Mistral | Medium 3.5 (API), Small line |
| Meta / Moonshot / Z.ai / DeepSeek | open weights too big for the box → run via API (Llama 4, Kimi K3 / K2.7, GLM-5.3, DeepSeek V4 if vision) |

## Tier 2 — local, fits the 3090, on Ollama today
Ordered by how much I'd bet on them. Sizes are Ollama Q4 tags.

| Model | Ollama tag | Disk | Fits 64K ctx? | Why |
|---|---|---|---|---|
| Qwen3.8 27B | `qwen3.8:27b` | 18 GB | yes (20.5 GB measured) | the incumbent; baseline |
| Gemma 4 31B dense | `gemma4:31b` | 20 GB | tight, likely 32K | highest vision benchmarks at this tier (MMMU-Pro 76.9) |
| Gemma 4 26B-A4B MoE | `gemma4:26b` | 18 GB | yes | fast (3.8B active); vision + tool use |
| Qwen3.6 27B | `qwen3.6:27b` | 17 GB | yes | April 2026, "state-of-the-art local vision" per InsiderLLM; Ollama lists it under vision now |
| Qwen3.6 35B-A3B MoE | `qwen3.6:35b` | 22 GB | 32K at most | faster than 27B dense; image + video native |
| Muse Glimmer 30B | `muse-glimmer:30b` | 18 GB | yes | Meta's local-agent model: failure recovery, long tasks. Same lineage as the Muse review seat |
| Qwen3.5 27B / 35B | `qwen3.5:27b`, `qwen3.5:35b` | ~17 / 22 GB | yes / 32K | prior gen; cheap "did the family improve" datapoint |
| Qwen3-VL 32B / 30B-A3B | `qwen3-vl:32b`, `qwen3-vl:30b` | ~20 / 19 GB | 32K / yes | the dedicated VL line; 30B-A3B is the speed pick |
| Gemma 4 12B | `gemma4:12b` | ~8 GB | yes | small-tier reference |
| Qwen3.5 9B / 4B | `qwen3.5:9b`, `qwen3.5:4b` | 6 / 3 GB | yes | how low can a model go and still leave the house |
| MiniCPM-V 4.5 8B | `minicpm-v4.5:8b` | ~5 GB | yes | "GPT-4o level" edge VLM claim; screenshot-heavy training |

## Tier 3 — local, specialized, worth one run each
| Model | How to run | Why it might beat a generalist |
|---|---|---|
| **UI-TARS-1.5 7B** (ByteDance) | HF weights via llama.cpp / vLLM; not on Ollama | GUI/game agent model trained on screenshots → actions; the 1.5 release explicitly claims game-scenario strength. Needs an adapter: it emits its own action grammar, we map to ALLOWED |
| GLM-4.6V-Flash 9B | GGUF via llama.cpp | Z.ai's small VLM tuned for local, low latency |
| Qwen3-VL 8B | `qwen3-vl:8b` | best small VL for OCR/screenshots per the 2025 reviews |

## Checked and OUT (for the box)
| Model | Why not |
|---|---|
| Ling-2.6-1T (inclusionAI) | text-only, 1T params. The "Ling benching well" news is a cloud model, not a local vision candidate |
| Ming-flash-omni 2.0 (Ling's multimodal sibling) | 100B total / 6B active; ~60 GB at Q4, no Ollama build. API-only if at all |
| GLM-5.3-Flash | 320B total / 18B active; multimodal but far past 24 GB |
| Nemotron 3 33B Omni | 28 GB on disk at Q4 |
| Llama 4 Scout | ~55 GB; run via API in Tier 1 |
| Kimi K3 / K2.7, MiniMax M3 | frontier-sized open weights; Tier 1 via API |

## Open questions
- Ollama vision for `qwen3.6` was reported broken in spring 2026 (mmproj not wired); the library now lists it under vision. Verify with one turn before scheduling a run.
- Context per model: measure VRAM at 64K for each 27B+ entry; set `ctx` in models.yaml to what fits, never the model's max.
- UI-TARS adapter is the only Tier 3 entry that is real work; file separately if we want it.

Sources: Ollama library vision filter (ollama.com/search?c=vision) and model pages for glm-5.3-flash, muse-glimmer, nemotron3;
insiderllm.com/guides/vision-models-locally; morphllm.com/best-ollama-models; github.com/inclusionAI/Ming;
openrouter.ai/inclusionai/ling-2.6-1t; github.com/bytedance/ui-tars.
