# PokéBench providers

`providers.py` uses Python 3.10+ and `requests`, with no provider SDKs. Importing it
makes no requests. `run_benchmark.py` drives these adapters; they also work standalone.

```python
from providers import get_provider

provider = get_provider("ollama", "qwen3.8:27b", num_ctx=65536, temperature=0.6)
plan, thinking, tokens = provider.chat(system, user, image_b64, schema, think="low")
usd = provider.cost(tokens)
```

`chat(system: str, user: str, image_b64: str, schema: dict, think: str)` returns
`(plan: dict, thinking: str, tokens: {"prompt": int, "completion": int})`.
Pass a raw base64 **PNG**, without a data-URL prefix, and the harness JSON schema.
`thinking` contains only text the API exposes, or `""` (always empty for OpenAI
Chat Completions). Gemini completion totals include its separately reported
thinking tokens. HTTP failures propagate as `requests` exceptions; missing keys,
invalid JSON, refusals, and incomplete hosted responses raise clear errors.

| Provider | Environment | Settings |
| --- | --- | --- |
| `ollama` | `OLLAMA_HOST`, optional; defaults to the existing harness host | `num_ctx=65536`, `temperature=0.6`; 30-minute keep-alive |
| `anthropic` | `ANTHROPIC_API_KEY`, required | Messages API; `max_tokens=8192` |
| `openai` | `OPENAI_API_KEY`, required | Chat Completions; `max_tokens=8192`; temperature omitted |
| `google` | `GEMINI_API_KEY`, required | generateContent; `max_tokens=8192`, `temperature=0.6` |

All constructors accept `timeout=600`, `input_cost_per_mtok`, and
`output_cost_per_mtok`. Cloud credentials are checked on construction. `cost()`
computes `(prompt * input_rate + completion * output_rate) / 1_000_000` in USD.
Both cloud rates must be supplied to calculate cost; Ollama always returns `0.0`.
This is a standard-rate estimate, without cache discounts or other billing tiers.

Ollama forwards `think` unchanged. Hosted adapters interpret `""` or `"default"`
as API defaults. Anthropic uses adaptive thinking with the requested effort;
OpenAI uses `reasoning_effort`; Gemini 3+ uses `thinkingLevel` and requests thought
summaries. `"off"`/`"none"` requests disabled thinking (Gemini budget zero).
Supported effort levels and disabling thinking depend on the model; unsupported
settings produce an API error. The benchmark runs every model at `high`, per §0 of the spec;
`low` is only for cheap smoke tests.

Schemas should use the harness's common subset: named object properties, arrays,
strings/numbers/booleans, enums, and required fields. Anthropic/OpenAI close objects
with `additionalProperties: false`. OpenAI also requires every declared field,
including optional harness strings (which can be empty). Gemini receives OpenAPI
type names through `responseSchema`. The caller's schema is never mutated.

To add a model, append an entry under `models:` in `models.yaml`, with a unique
`key` and all the existing fields. `api_model_id` goes to the API; `params` is model
size metadata, `quant` is a quantization label or null, and `context` is a token
count. Use quoted ISO dates (`"YYYY-MM-DD"`), or null when unknown. The hosted seed
rows contain **PLACEHOLDER prices and dates**, not verified model facts; replace
them before reporting benchmark costs or release chronology.

A runner can load the registry with PyYAML (`yaml.safe_load`); YAML parsing is
separate from the adapters and is not needed to import `providers.py`:

```python
import yaml
from providers import get_provider

with open("models.yaml") as source:
    models = yaml.safe_load(source)["models"]
entry = next(model for model in models if model["key"] == "qwen3.8:27b")
opts = {name: entry[name] for name in ("input_cost_per_mtok", "output_cost_per_mtok")}
if entry["provider"] == "ollama":
    opts["num_ctx"] = entry["context"]
provider = get_provider(entry["provider"], entry["api_model_id"], **opts)
# When running: provider.chat(system, user, image_b64, schema, entry["think"])
```

Wire-format references: [Anthropic JSON outputs](https://platform.claude.com/docs/en/build-with-claude/structured-outputs),
[OpenAI structured outputs](https://developers.openai.com/api/docs/guides/structured-outputs),
and [Gemini generateContent](https://ai.google.dev/api/generate-content).
