"""Small, synchronous PokéBench adapters. Only third-party dependency: requests."""

from abc import ABC, abstractmethod
from copy import deepcopy
import json
import math
import os
from urllib.parse import quote

import requests


ChatResult = tuple[dict, str, dict[str, int]]


def _plan(content: str) -> dict:
    """Reject empty, malformed, or non-object responses before returning a plan."""
    try:
        plan = json.loads(content)
    except (TypeError, ValueError) as exc:
        raise ValueError("Provider did not return a valid JSON plan") from exc
    if not isinstance(plan, dict):
        raise ValueError("Provider plan must be a JSON object")
    return plan


def _schema_for(schema: dict, provider: str) -> dict:
    """Translate the harness's object/array schema without changing the caller's copy."""
    result = deepcopy(schema)
    if "properties" in result:
        result["properties"] = {
            name: _schema_for(value, provider)
            for name, value in result["properties"].items()
        }
    if isinstance(result.get("items"), dict):
        result["items"] = _schema_for(result["items"], provider)
    for keyword in ("anyOf", "allOf", "oneOf"):
        if keyword in result:
            result[keyword] = [_schema_for(value, provider) for value in result[keyword]]
    for keyword in ("$defs", "definitions"):
        if keyword in result:
            result[keyword] = {
                name: _schema_for(value, provider) for name, value in result[keyword].items()
            }
    if provider == "google":
        # generateContent.responseSchema uses OpenAPI types, not full JSON Schema.
        if isinstance(result.get("type"), str):
            result["type"] = result["type"].upper()
        result.pop("additionalProperties", None)
    elif result.get("type") == "object" or "properties" in result:
        result["additionalProperties"] = False
        if provider == "openai":
            # Every declared field is returned; optional string fields may be empty.
            result["required"] = list(result.get("properties", {}))
    return result


class Provider(ABC):
    """One stateless screenshot-to-plan turn, plus a registry-based USD estimate."""

    api_key_env = ""

    def __init__(
        self,
        model: str,
        *,
        input_cost_per_mtok: float | None = None,
        output_cost_per_mtok: float | None = None,
        timeout: float = 600,
    ):
        self.model = model
        self.timeout = timeout
        self.input_cost_per_mtok = input_cost_per_mtok
        self.output_cost_per_mtok = output_cost_per_mtok
        for rate in (input_cost_per_mtok, output_cost_per_mtok):
            if rate is not None and (not math.isfinite(rate) or rate < 0):
                raise ValueError("Model token rates must be finite, nonnegative USD per million")
        self.api_key = ""
        if self.api_key_env:
            self.api_key = os.environ.get(self.api_key_env, "").strip()
            if not self.api_key:
                raise ValueError(f"{type(self).__name__} requires {self.api_key_env}")

    @abstractmethod
    def chat(
        self, system: str, user: str, image_b64: str, schema: dict, think: str
    ) -> ChatResult:
        """Return (plan, available thinking text, {prompt: int, completion: int})."""
        raise NotImplementedError

    def cost(self, tokens: dict[str, int]) -> float | None:
        """Estimate USD at the supplied standard input/output rates (no cache tiers).
        Returns None when rates are unset, so a run records cost_usd: null rather than a
        fabricated number — an unverified price is worse than an honest unknown."""
        if self.input_cost_per_mtok is None or self.output_cost_per_mtok is None:
            return None
        return (
            tokens["prompt"] * self.input_cost_per_mtok
            + tokens["completion"] * self.output_cost_per_mtok
        ) / 1_000_000

    def _post(self, url: str, payload: dict, headers: dict | None = None) -> dict:
        response = requests.post(url, json=payload, headers=headers, timeout=self.timeout)
        response.raise_for_status()
        return response.json()


class OllamaProvider(Provider):
    """The qwen_red.ask() wire contract, including its local defaults."""

    def __init__(self, model: str, *, num_ctx: int = 65536, temperature: float = 0.6, **opts):
        super().__init__(model, **opts)
        self.host = os.environ.get("OLLAMA_HOST", "http://<server-host>:11434").rstrip("/")
        self.num_ctx = num_ctx
        self.temperature = temperature

    def chat(
        self, system: str, user: str, image_b64: str, schema: dict, think: str
    ) -> ChatResult:
        body = self._post(f"{self.host}/api/chat", {
            "model": self.model, "stream": False, "format": schema, "think": think,
            "keep_alive": "30m",
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user, "images": [image_b64]},
            ],
            "options": {"num_ctx": self.num_ctx, "temperature": self.temperature, "num_predict": 8192},
        })
        message = body["message"]
        return _plan(message["content"]), message.get("thinking", "") or "", {
            "prompt": int(body.get("prompt_eval_count", 0)),
            "completion": int(body.get("eval_count", 0)),
        }

    def cost(self, tokens: dict[str, int]) -> float:
        return 0.0


class AnthropicProvider(Provider):
    """Messages API with image blocks, JSON output schema, and adaptive thinking."""

    api_key_env = "ANTHROPIC_API_KEY"

    def __init__(self, model: str, *, max_tokens: int = 8192, **opts):
        super().__init__(model, **opts)
        self.max_tokens = max_tokens

    def chat(
        self, system: str, user: str, image_b64: str, schema: dict, think: str
    ) -> ChatResult:
        payload = {
            "model": self.model, "max_tokens": self.max_tokens, "system": system,
            "messages": [{"role": "user", "content": [
                {"type": "image", "source": {
                    "type": "base64", "media_type": "image/png", "data": image_b64,
                }},
                {"type": "text", "text": user},
            ]}],
            "output_config": {"format": {
                "type": "json_schema", "schema": _schema_for(schema, "anthropic"),
            }},
        }
        effort = think.strip().lower()
        if effort in {"off", "none"}:
            payload["thinking"] = {"type": "disabled"}
        elif effort not in {"", "default"}:
            # budget_tokens extended thinking (adaptive/effort is rejected by Haiku 4.5 and kin);
            # it coexists with output_config json_schema on this API version. max_tokens must
            # exceed the budget, so bump it when a high budget would meet the configured ceiling.
            budget = {"low": 2048, "medium": 4096, "high": 8192}.get(effort, 4096)
            payload["thinking"] = {"type": "enabled", "budget_tokens": budget}
            if payload["max_tokens"] <= budget:
                payload["max_tokens"] = budget + 4096
        headers = {
            "x-api-key": self.api_key, "anthropic-version": "2023-06-01",
            "content-type": "application/json",
        }
        # Org-scoped keys must name a workspace or the API 400s before any inference.
        workspace = os.environ.get("ANTHROPIC_WORKSPACE_ID", "").strip()
        if workspace:
            headers["anthropic-workspace-id"] = workspace
        body = self._post("https://api.anthropic.com/v1/messages", payload, headers)
        if body.get("stop_reason") in {"max_tokens", "refusal"}:
            raise ValueError(f"Anthropic returned no complete plan: {body['stop_reason']}")
        blocks = body.get("content", [])
        content = "".join(block["text"] for block in blocks if block.get("type") == "text")
        thinking = "\n".join(
            block["thinking"] for block in blocks if block.get("type") == "thinking"
        )
        usage = body.get("usage", {})
        return _plan(content), thinking, {
            "prompt": int(usage.get("input_tokens", 0)),
            "completion": int(usage.get("output_tokens", 0)),
        }


class OpenAIProvider(Provider):
    """Chat Completions with a PNG data URL and strict JSON schema output."""

    api_key_env = "OPENAI_API_KEY"
    base_url = "https://api.openai.com/v1"

    def __init__(self, model: str, *, max_tokens: int = 8192, **opts):
        super().__init__(model, **opts)
        self.max_tokens = max_tokens

    def chat(
        self, system: str, user: str, image_b64: str, schema: dict, think: str
    ) -> ChatResult:
        payload = {
            "model": self.model, "max_completion_tokens": self.max_tokens,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": [
                    {"type": "text", "text": user},
                    {"type": "image_url", "image_url": {
                        "url": f"data:image/png;base64,{image_b64}",
                    }},
                ]},
            ],
            "response_format": {"type": "json_schema", "json_schema": {
                "name": "game_plan", "strict": True,
                "schema": _schema_for(schema, "openai"),
            }},
        }
        effort = think.strip().lower()
        if effort not in {"", "default"}:
            payload["reasoning_effort"] = "none" if effort == "off" else effort
        body = self._post(f"{self.base_url}/chat/completions", payload, {
            "Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json",
        })
        choices = body.get("choices", [])
        if not choices:
            raise ValueError("OpenAI returned no choices")
        choice = choices[0]
        message = choice["message"]
        if message.get("refusal") or choice.get("finish_reason") in {"length", "content_filter", "error"}:
            raise ValueError("OpenAI refused or could not finish the JSON plan")
        usage = body.get("usage", {})
        # Chat Completions omits reasoning; OpenRouter may return message.reasoning, so keep it.
        return _plan(message.get("content")), message.get("reasoning") or "", {
            "prompt": int(usage.get("prompt_tokens", 0)),
            "completion": int(usage.get("completion_tokens", 0)),
        }


class GoogleProvider(Provider):
    """Gemini generateContent with inline PNG data and responseSchema."""

    api_key_env = "GEMINI_API_KEY"

    def __init__(self, model: str, *, max_tokens: int = 8192, temperature: float = 0.6, **opts):
        super().__init__(model, **opts)
        self.max_tokens = max_tokens
        self.temperature = temperature

    def chat(
        self, system: str, user: str, image_b64: str, schema: dict, think: str
    ) -> ChatResult:
        config = {
            "responseMimeType": "application/json", "responseSchema": _schema_for(schema, "google"),
            "maxOutputTokens": self.max_tokens, "temperature": self.temperature,
        }
        effort = think.strip().lower()
        if effort in {"off", "none"}:
            config["thinkingConfig"] = {"thinkingBudget": 0}
        elif effort not in {"", "default"}:
            config["thinkingConfig"] = {"thinkingLevel": effort.upper(), "includeThoughts": True}
        model_id = quote(self.model.removeprefix("models/"), safe="")
        body = self._post(
            f"https://generativelanguage.googleapis.com/v1beta/models/{model_id}:generateContent",
            {
                "systemInstruction": {"parts": [{"text": system}]},
                "contents": [{"role": "user", "parts": [
                    {"text": user}, {"inlineData": {"mimeType": "image/png", "data": image_b64}},
                ]}],
                "generationConfig": config,
            },
            {"x-goog-api-key": self.api_key, "Content-Type": "application/json"},
        )
        candidates = body.get("candidates", [])
        if not candidates:
            reason = body.get("promptFeedback", {}).get("blockReason", "no candidates")
            raise ValueError(f"Google returned no plan: {reason}")
        candidate = candidates[0]
        if candidate.get("finishReason", "STOP") != "STOP":
            raise ValueError(f"Google could not finish the JSON plan: {candidate['finishReason']}")
        parts = candidate.get("content", {}).get("parts", [])
        content = "".join(part.get("text", "") for part in parts if not part.get("thought"))
        thinking = "\n".join(part["text"] for part in parts if part.get("thought") and "text" in part)
        usage = body.get("usageMetadata", {})
        return _plan(content), thinking, {
            "prompt": int(usage.get("promptTokenCount", 0)),
            "completion": int(usage.get("candidatesTokenCount", 0)) + int(usage.get("thoughtsTokenCount", 0)),
        }


class OpenRouterProvider(OpenAIProvider):
    """One key routes to many providers (BYOK) through OpenRouter's OpenAI-compatible endpoint.
    Model ids are namespaced, e.g. 'qwen/qwen-2.5-vl-72b-instruct'. Vision and JSON-schema output
    pass through; a model whose backend ignores strict schema trips _plan's parse guard, which the
    turn loop already treats as a skipped turn rather than a crash."""

    api_key_env = "OPENROUTER_API_KEY"
    base_url = "https://openrouter.ai/api/v1"


def get_provider(provider_name: str, model: str, **opts) -> Provider:
    """Construct an adapter; opts are constructor settings and registry token rates."""
    providers = {
        "ollama": OllamaProvider, "anthropic": AnthropicProvider,
        "openai": OpenAIProvider, "google": GoogleProvider,
        "openrouter": OpenRouterProvider,
    }
    try:
        provider = providers[provider_name.strip().lower()]
    except KeyError:
        raise ValueError(f"Unknown provider {provider_name!r}; choose {', '.join(providers)}") from None
    return provider(model, **opts)
