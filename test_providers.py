# Run: python3 test_providers.py
# Set ANTHROPIC_API_KEY, OPENAI_API_KEY, and/or GEMINI_API_KEY to test cloud providers.
# Ollama always runs; optional overrides: OLLAMA_HOST and OLLAMA/ANTHROPIC/OPENAI/GEMINI_MODEL.

import base64
import io
import os
import sys

sys.dont_write_bytecode = True

from PIL import Image

import providers


# Same schema as qwen_red, without importing its game harness.
SCHEMA = {
    "type": "object",
    "properties": {
        "thought": {"type": "string"},
        "actions": {"type": "array", "items": {"type": "string"}},
        "key_moment": {"type": "string"},
        "notes": {"type": "string"},
    },
    "required": ["thought", "actions"],
}

# Cloud defaults support vision and structured output; keep generation small.
PROVIDERS = (
    ("ollama", "", "OLLAMA_MODEL", "qwen3.8:27b", "low", {"num_ctx": 2048}),
    ("anthropic", "ANTHROPIC_API_KEY", "ANTHROPIC_MODEL", "claude-haiku-4-5", "off", {"max_tokens": 256}),
    ("openai", "OPENAI_API_KEY", "OPENAI_MODEL", "gpt-4.1-mini", "default", {"max_tokens": 256}),
    ("google", "GEMINI_API_KEY", "GEMINI_MODEL", "gemini-2.5-flash", "off", {"max_tokens": 256}),
)


def main():
    png = io.BytesIO()
    Image.new("RGB", (32, 32), (255, 0, 0)).save(png, format="PNG")
    image_b64 = base64.b64encode(png.getvalue()).decode("ascii")
    failed_with_key = False

    for name, key_env, model_env, default_model, think, opts in PROVIDERS:
        has_key = bool(os.environ.get(key_env, "").strip()) if key_env else False
        if key_env and not has_key:
            print(f"SKIP {name}: {key_env} is not set", flush=True)
            continue

        model = os.environ.get(model_env, "").strip() or default_model
        tokens = {}
        error = ""
        try:
            plan, thinking, tokens = providers.get_provider(
                name, model, timeout=120, **opts
            ).chat(
                system="Return a brief JSON plan matching the schema.",
                user="Name the image color in thought; set actions to [\"wait_60\"].",
                image_b64=image_b64,
                schema=SCHEMA,
                think=think,
            )
            assert isinstance(plan, dict), "plan must be a dict"
            assert isinstance(plan.get("thought"), str), "plan.thought must be a string"
            assert isinstance(plan.get("actions"), list), "plan.actions must be a list"
            assert all(isinstance(a, str) for a in plan["actions"]), "actions must contain strings"
            assert isinstance(thinking, str), "thinking must be a string"
            assert isinstance(tokens, dict), "tokens must be a dict"
            for field in ("prompt", "completion"):
                assert type(tokens.get(field)) is int, f"tokens.{field} must be an int"
        except Exception as exc:
            error = f"{type(exc).__name__}: {' '.join(str(exc).split())}"
            failed_with_key |= has_key

        usage = tokens if isinstance(tokens, dict) else {}
        status = "FAIL" if error else "PASS"
        detail = f"; {error}" if error else ""
        # Only keyed-provider failures affect the exit code, as requested.
        if error and not key_env:
            detail += " (non-fatal: Ollama requires no API key)"
        print(
            f"{status} {name} ({model}): "
            f"tokens prompt={usage.get('prompt', 'n/a')} "
            f"completion={usage.get('completion', 'n/a')}{detail}",
            flush=True,
        )

    return int(failed_with_key)


if __name__ == "__main__":
    sys.exit(main())
