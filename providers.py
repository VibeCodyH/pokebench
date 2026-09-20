"""Small, synchronous PokéBench adapters. Only third-party dependency: requests."""

from abc import ABC, abstractmethod
from copy import deepcopy
import json
import math
import os
import time
from types import SimpleNamespace
from urllib.parse import quote

import requests


ChatResult = tuple[dict, str, dict[str, int]]


def _plan(content: str) -> dict:
    """Reject empty, malformed, or non-object responses before returning a plan."""
    try:
        plan = json.loads(content)
    except (TypeError, ValueError) as exc:
        raise _plan_error("Provider did not return a valid JSON plan", content) from exc
    if not isinstance(plan, dict):
        raise _plan_error("Provider plan must be a JSON object", content)
    return plan


def _plan_error(message: str, content, usage: dict | None = None) -> ValueError:
    """Carry the raw model output on the error so the run log can show empty vs malformed."""
    error = ValueError(message)
    error.raw_output = (content if isinstance(content, str) else repr(content))[:2000]
    error.usage = usage  # the tokens this failed attempt still cost; the runner logs them
    return error


def _plan_with_usage(content, usage: dict) -> dict:
    """_plan(), but a parse failure keeps the usage the response reported."""
    try:
        return _plan(content)
    except ValueError as exc:
        exc.usage = usage
        raise


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
        # requests treats this as the gap between bytes, not the length of the call. For the
        # buffered adapters that works out to the whole turn; the streamed OpenAI-compatible
        # path turns it into a silence window instead, so those rows can set it far lower.
        timeout: float = 600,
        # Wall clock for ONE model call, which `timeout` cannot supply on a streamed response:
        # a backend that keeps emitting frames forever never trips a silence window. The
        # default is deliberately loose. Worst SUCCESSFUL call across every run on the board is
        # 403.1s (azure-grok-4-3), so this clears the measured ceiling by better than 2x.
        # ★ Keep it that way: per-row is the TIGHTENING mechanism, not this number. Too tight a
        # default does not fail loudly, it turns a merely slow model into `provider_error` after
        # an hour of compute, and a provider_error run is barred from the board.
        max_call_s: float = 900,
    ):
        self.model = model
        self.timeout = timeout
        if not math.isfinite(max_call_s) or max_call_s <= 0:
            raise ValueError("max_call_s must be a finite positive number of seconds")
        self.max_call_s = max_call_s
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

    def _post_stream(self, url: str, payload: dict, headers: dict | None = None) -> dict:
        """Stream an OpenAI-style completion and rebuild the non-streaming response shape.

        This is not about latency. requests' read timeout has always been the gap between
        bytes, not the total call, but a buffered response sends nothing until the model has
        finished, so the whole turn had to fit inside `timeout` and a socket that died mid-call
        looked exactly like a model that was still thinking. One did: an Azure request to Kimi
        sat with an ESTABLISHED connection and zero bytes queued in either direction while the
        same deployment answered an independent probe in 3.9s, and the harness could only wait
        out the full budget. With SSE frames arriving, `timeout` becomes a silence window and
        that stall is caught in seconds. Measured inter-chunk gaps were at most 1.6s across
        every model tried, while time to the FIRST chunk reached 178s on grok-4.6 because Azure
        buffers the reasoning phase, so the window has to clear a model's worst TTFT, not its
        streaming rate. That is why it is per-model rather than one global number.

        The silence window has a blind spot that `max_call_s` covers: a stream that keeps
        arriving can never trip it. gpt-6-astra did exactly that twice, delivering ~37 KB/s
        into a single turn for over ten minutes with the 90s poll rearming on every chunk, and
        nothing in the harness could end it. The deadline is only observed when a chunk lands,
        so the overshoot is bounded by one `timeout` and no watchdog thread is needed.
        """
        deadline = time.monotonic() + self.max_call_s   # started before the post: TTFT counts
        response = requests.post(url, json=payload, headers=headers,
                                 timeout=self.timeout, stream=True)
        content, reasoning, refusal = [], [], []
        finish_reason, usage = None, None
        try:
            if not response.ok:
                # Materialize the error body before raising: the turn loop reads
                # exc.response.text to spot the billing and auth failures it must not retry,
                # and a streamed response has not fetched it yet.
                response.content
                response.raise_for_status()
            # Set unconditionally. SSE is UTF-8 by specification, but requests derives the
            # encoding from the header, and get_encoding_from_headers answers ISO-8859-1 for any
            # text/* type that omits a charset. That is truthy, so falling back only when it is
            # empty would silently decode UTF-8 as Latin-1: still valid JSON, still a parseable
            # plan, but every accented character mangled in the thought text the overlay renders.
            response.encoding = "utf-8"
            # delimiter given explicitly: without it, iter_lines uses str.splitlines(), which
            # also breaks on U+2028, U+2029 and U+0085. Those are legal raw inside a JSON string,
            # and one in the thought text cut the frame mid-string: the remainder no longer
            # started with "data:", so it was dropped, and the head failed to parse.
            for line in response.iter_lines(decode_unicode=True, delimiter="\n"):
                # Before the blank/comment skip, so keepalive frames cannot hold the call open.
                if time.monotonic() > deadline:
                    raise _call_expired(self.max_call_s, "".join(content), "".join(reasoning))
                line = line.rstrip("\r")
                # Blank separators, and comment frames like OpenRouter's ": OPENROUTER PROCESSING"
                if not line or line.startswith(":") or not line.startswith("data:"):
                    continue
                data = line[5:].strip()
                if data == "[DONE]":
                    break
                frame = json.loads(data)
                if frame.get("error"):
                    raise _stream_error(frame["error"])
                # include_usage delivers this as its own frame, with choices empty.
                if frame.get("usage"):
                    usage = frame["usage"]
                for choice in frame.get("choices") or []:
                    delta = choice.get("delta") or {}
                    content.append(delta.get("content") or "")
                    # reasoning on most backends, reasoning_content on xAI and DeepSeek
                    reasoning.append(delta.get("reasoning") or delta.get("reasoning_content") or "")
                    refusal.append(delta.get("refusal") or "")
                    finish_reason = choice.get("finish_reason") or finish_reason
        finally:
            response.close()
        if usage is None:
            # Defaulting to zeros here would record fabricated token counts and price them,
            # which is the failure cost() refuses to commit. A backend that drops
            # stream_options has to fail the turn instead.
            raise ValueError("stream ended without a usage frame; stream_options unsupported?")
        message = {"content": "".join(content), "reasoning": "".join(reasoning),
                   "reasoning_content": "".join(reasoning), "refusal": "".join(refusal)}
        return {"choices": [{"message": message, "finish_reason": finish_reason}], "usage": usage}


def _call_expired(limit: float, content: str, reasoning: str) -> TimeoutError:
    """A runaway stream has to reach the turn loop as a RETRYABLE failure: no .response means
    the loop reads status None and an empty body, so it backs off and replays the same turn
    rather than aborting the run. Carry a head of what the model was emitting -- that text is
    the only evidence of WHY a call ran away, and the alternative is a log line saying a call
    took too long with nothing to look at. Truncated because raw_output is written to
    log.jsonl verbatim and the stream that prompted this guard reached 13.9 MB."""
    exc = TimeoutError(f"model call exceeded max_call_s={limit:g}s while the stream was still "
                       f"delivering ({len(content)} content + {len(reasoning)} reasoning chars)")
    exc.raw_output = (reasoning + content)[:2000]
    return exc


def _stream_error(error) -> ValueError:
    """An error frame after HTTP 200 (OpenRouter documents a 402 arriving this way) must reach
    the turn loop looking like an HTTP failure: it reads exc.response.status_code and
    exc.response.text to decide that billing and auth errors are not worth retrying. A bare
    ValueError has neither, so a depleted key was retried for the whole error window."""
    text = json.dumps(error)[:500]
    code = error.get("code") if isinstance(error, dict) else None
    exc = ValueError(f"stream error: {text}")
    exc.response = SimpleNamespace(status_code=code if isinstance(code, int) else None, text=text)
    return exc


class OllamaProvider(Provider):
    """The qwen_red.ask() wire contract, including its local defaults."""

    def __init__(self, model: str, *, num_ctx: int = 65536, temperature: float = 0.6, max_tokens: int | None = None, **opts):
        super().__init__(model, **opts)
        self.host = os.environ.get("OLLAMA_HOST", "http://localhost:11434").rstrip("/")
        self.num_ctx = num_ctx
        self.temperature = temperature
        # num_predict; summary.json reports it as max_output_tokens. Ollama counts thinking
        # against it, and a capped thinking model spends the cap on thought and returns "" --
        # qwen3.8:27b did that 11 times in 242 turns at 8192 (2026-09-11). None sends -1, which
        # is ollama's "unlimited", so a model stops when it is done rather than when we cut it off.
        self.max_tokens = max_tokens

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
            "options": {"num_ctx": self.num_ctx, "temperature": self.temperature,
                        "num_predict": -1 if self.max_tokens is None else self.max_tokens},
        })
        message = body["message"]
        usage = {"prompt": int(body.get("prompt_eval_count", 0)), "completion": int(body.get("eval_count", 0))}
        return _plan_with_usage(message["content"], usage), message.get("thinking", "") or "", usage

    def cost(self, tokens: dict[str, int]) -> float:
        return 0.0


class AnthropicProvider(Provider):
    """Messages API with image blocks, JSON output schema, and thinking.

    Thinking has TWO mutually exclusive request shapes and the API hard-400s on the wrong one,
    so `thinking_style` is a per-row choice rather than something to detect:

      budget   (default) `thinking: {type: enabled, budget_tokens: N}`. Haiku 4.5 and kin;
               they reject adaptive ("adaptive thinking is not supported on this model").
      adaptive `thinking: {type: adaptive}` + `output_config.effort`. The Claude 5 family
               rejects the budget shape with "thinking.type.enabled is not supported for this
               model. Use thinking.type.adaptive and output_config.effort" — verified against
               claude-opus-5 and claude-sonnet-5 on 2026-09-17.

    Both bill thinking inside `output_tokens`, so cost accounting is the same either way.
    """

    api_key_env = "ANTHROPIC_API_KEY"

    # Unlike every other API here, Anthropic REQUIRES max_tokens, so it cannot be omitted to
    # let the model use its own maximum. This is a high default rather than a real ceiling;
    # models.yaml can raise it per row, and must, for a model that supports more.
    DEFAULT_MAX_TOKENS = 32000
    THINKING_STYLES = ("budget", "adaptive")

    def __init__(self, model: str, *, max_tokens: int | None = None,
                 thinking_style: str = "budget", cache_system: bool = True, **opts):
        super().__init__(model, **opts)
        self.max_tokens = self.DEFAULT_MAX_TOKENS if max_tokens is None else max_tokens
        if thinking_style not in self.THINKING_STYLES:
            raise ValueError(
                f"thinking_style must be one of {self.THINKING_STYLES}, got {thinking_style!r}"
            )
        self.thinking_style = thinking_style
        self.cache_system = cache_system

    def chat(
        self, system: str, user: str, image_b64: str, schema: dict, think: str
    ) -> ChatResult:
        # The system prompt is the only stable prefix the harness has: everything in the user
        # block (notes, recent turns, state, map) changes every turn, and NOTES sits at the top
        # of it, so no longer prefix is cacheable without reordering the prompt — which would
        # change PROMPT_SHA and break comparability with the board. Every other provider here
        # caches automatically and for free; Anthropic is the one that needs asking, so ask.
        # ~1.3k tokens on prompt v21, which clears Opus/Sonnet's 1024-token minimum but NOT
        # Haiku's 2048, where the API declines to cache and simply bills normally.
        system_block = [{"type": "text", "text": system,
                         "cache_control": {"type": "ephemeral"}}] if self.cache_system else system
        payload = {
            "model": self.model, "max_tokens": self.max_tokens, "system": system_block,
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
            if self.thinking_style == "adaptive":
                # The model decides how much to think; effort sets the ceiling. No max_tokens
                # bump, because there is no separate budget to clear.
                payload["thinking"] = {"type": "adaptive"}
                payload["output_config"]["effort"] = effort
            else:
                # budget_tokens extended thinking; it coexists with output_config json_schema on
                # this API version. max_tokens must exceed the budget, so bump it when a high
                # budget would meet the configured ceiling.
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
        # ⚠️ With caching on, `input_tokens` counts only the UNCACHED remainder: the cached
        # prefix is reported separately and would otherwise vanish. `prompt` has to stay
        # "tokens the model saw" or tokens_in silently drops ~1.3k a turn and stops meaning
        # the same thing as every other row on the board (OpenRouter reports the full count
        # whether or not it served from cache). The split rides along for cost().
        write = int(usage.get("cache_creation_input_tokens", 0))
        read = int(usage.get("cache_read_input_tokens", 0))
        return _plan(content), thinking, {
            "prompt": int(usage.get("input_tokens", 0)) + write + read,
            "completion": int(usage.get("output_tokens", 0)),
            "cache_write": write,
            "cache_read": read,
        }

    def cost(self, tokens: dict[str, int]) -> float | None:
        """Cache-aware, unlike the base estimate: a 5-minute cache write bills at 1.25x the
        input rate and a read at 0.1x, so pricing the whole prompt at the standard rate would
        overstate a cached run by most of the system prompt on every turn after the first."""
        if self.input_cost_per_mtok is None or self.output_cost_per_mtok is None:
            return None
        write = tokens.get("cache_write", 0)
        read = tokens.get("cache_read", 0)
        uncached = max(0, tokens["prompt"] - write - read)
        return (
            uncached * self.input_cost_per_mtok
            + write * self.input_cost_per_mtok * 1.25
            + read * self.input_cost_per_mtok * 0.1
            + tokens["completion"] * self.output_cost_per_mtok
        ) / 1_000_000


class OpenAIProvider(Provider):
    """Chat Completions with a PNG data URL and strict JSON schema output."""

    api_key_env = "OPENAI_API_KEY"
    base_url = "https://api.openai.com/v1"

    def __init__(self, model: str, *, max_tokens: int | None = None,
                 structured_output: bool = True, **opts):
        super().__init__(model, **opts)
        self.max_tokens = max_tokens
        # Some backends (OpenRouter :free tiers on Novita, 2026-09-15) 400 on response_format.
        # The SYSTEM prompt already demands JSON in the schema's shape, so a row can set
        # `structured_output: false` and rely on the parse guard instead of the strict schema.
        self.structured_output = structured_output

    def _tokens(self, usage: dict) -> dict[str, int]:
        """OpenAI counts reasoning inside completion_tokens; a backend that does not
        overrides this so the recorded output matches what it actually bills."""
        return {
            "prompt": int(usage.get("prompt_tokens", 0)),
            "completion": int(usage.get("completion_tokens", 0)),
        }

    def _thinking(self, message: dict) -> str:
        """Where the visible reasoning lands, when a backend exposes it at all."""
        return message.get("reasoning") or ""

    def _tune_payload(self, payload: dict, effort: str) -> None:
        """Last word on the request body before it is sent. A backend whose dialect differs
        from OpenAI's (a thinking switch, a looser response_format) edits it here instead of
        copying chat()."""

    def chat(
        self, system: str, user: str, image_b64: str, schema: dict, think: str
    ) -> ChatResult:
        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": [
                    {"type": "text", "text": user},
                    {"type": "image_url", "image_url": {
                        "url": f"data:image/png;base64,{image_b64}",
                    }},
                ]},
            ],
            # Streamed so self.timeout means "silence", not "whole turn" — see _post_stream.
            "stream": True,
            "stream_options": {"include_usage": True},
        }
        if self.structured_output:
            payload["response_format"] = {"type": "json_schema", "json_schema": {
                "name": "game_plan", "strict": True,
                "schema": _schema_for(schema, "openai"),
            }}
        # Omitted entirely when uncapped, which lets the model use its own maximum.
        # #47 proposed a harness-wide default here and it was rejected on the numbers: the
        # worst SUCCESSFUL turn on the board spent 46,517 completion tokens (deepseek-flash),
        # so a default safe enough not to truncate a real plan sits too high to be much of a
        # guard, and it would silently change the request shape for all 14 published runs.
        # max_call_s is the provider-agnostic bound instead. Cap a row when you have measured it.
        if self.max_tokens is not None:
            payload["max_completion_tokens"] = self.max_tokens
        effort = think.strip().lower()
        if effort not in {"", "default"}:
            payload["reasoning_effort"] = "none" if effort == "off" else effort
        self._tune_payload(payload, effort)
        body = self._post_stream(f"{self.base_url}/chat/completions", payload, {
            "Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json",
        })
        choices = body.get("choices", [])
        if not choices:
            raise ValueError("OpenAI returned no choices")
        choice = choices[0]
        message = choice["message"]
        usage = body.get("usage", {})
        tokens = self._tokens(usage)
        if message.get("refusal") or choice.get("finish_reason") in {"length", "content_filter", "error"}:
            # name the finish_reason: "refused" and "ran out of output" are different failures to audit
            raise _plan_error(f"OpenAI refused or could not finish the JSON plan (finish_reason={choice.get('finish_reason')})",
                              message.get("content"), tokens)
        content = message.get("content")
        if not self.structured_output and isinstance(content, str):
            # No schema enforcement: tolerate a ```json fence or prose around the object.
            from qwen_red import _extract_json
            content = _extract_json(content)
        # Chat Completions omits reasoning; OpenRouter may return message.reasoning, so keep it.
        return _plan_with_usage(content, tokens), self._thinking(message), tokens


class GoogleProvider(Provider):
    """Gemini generateContent with inline PNG data and responseSchema.

    Two routes, same request body. GEMINI_API_KEY is AI Studio; GOOGLE_API_KEY is a Vertex
    Express key, which bills a Cloud project's credit instead. AI Studio wins when both are
    set, because an explicitly-set key is the more specific instruction.

    Vertex Express is Gemini-only and, measured 2026-09-12, Flash-only: publishers/anthropic
    and every non-Google publisher 404, as do gemini-3.8-pro and gemini-3.8-ultra. Do not
    plan a Model Garden run against this key.
    """

    api_key_env = ""  # resolved in __init__: either key is acceptable, so the base check is wrong
    AI_STUDIO = "https://generativelanguage.googleapis.com/v1beta/models"
    VERTEX_EXPRESS = "https://aiplatform.googleapis.com/v1/publishers/google/models"

    def __init__(self, model: str, *, max_tokens: int | None = None, temperature: float = 0.6, **opts):
        super().__init__(model, **opts)
        self.max_tokens = max_tokens
        self.temperature = temperature
        studio = os.environ.get("GEMINI_API_KEY", "").strip()
        express = os.environ.get("GOOGLE_API_KEY", "").strip()
        if studio:
            self.api_key, self.route, self.base_url = studio, "google-aistudio", self.AI_STUDIO
        elif express:
            self.api_key, self.route, self.base_url = express, "vertex-express", self.VERTEX_EXPRESS
        else:
            raise ValueError("GoogleProvider requires GEMINI_API_KEY (AI Studio) or GOOGLE_API_KEY (Vertex Express)")

    def chat(
        self, system: str, user: str, image_b64: str, schema: dict, think: str
    ) -> ChatResult:
        config = {
            "responseMimeType": "application/json", "responseSchema": _schema_for(schema, "google"),
            "temperature": self.temperature,
        }
        if self.max_tokens is not None:
            config["maxOutputTokens"] = self.max_tokens
        effort = think.strip().lower()
        if effort in {"off", "none"}:
            config["thinkingConfig"] = {"thinkingBudget": 0}
        elif effort not in {"", "default"}:
            config["thinkingConfig"] = {"thinkingLevel": effort.upper(), "includeThoughts": True}
        model_id = quote(self.model.removeprefix("models/"), safe="")
        body = self._post(
            f"{self.base_url}/{model_id}:generateContent",
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


class JevDecisionProvider(Provider):
    """TypeSafe's Jev on OpenRouter's /api/alpha/decisions endpoint.

    Not a chat model and not on /api/v1. Its modality is text->decisions: it returns a typed
    choice plus a probability over the options, never prose, so there is no content string to
    parse and `supported_parameters` is empty (no temperature, no max_tokens, no schema). The
    body is {model, state, questions} rather than messages.

    Two consequences for the benchmark, both real asterisks rather than bugs:

    - No vision. `image_b64` is discarded. The model gets the same system prompt and the same
      text STATE every other seat gets, and nothing else.
    - ONE action per turn, not up to six, because a `choice` question returns a single option.

    The run is an exhibition. Measured 2026-09-20 against the live endpoint: on a raw ASCII map
    with two solid rows of trees directly north and the goal stated as north, Jev answered
    walk_up at p=0.83. It reads the goal, not the map. That is what a System One model is, and
    it is the reason this cannot share a seat with the deliberating models."""

    api_key_env = "OPENROUTER_API_KEY"
    url = "https://openrouter.ai/api/alpha/decisions"

    # What each action does, in the model's own decision vocabulary. `criteria` IS the prompt
    # for a choice question, so these lines are load-bearing in a way a chat enum is not.
    ACTION_CRITERIA = {
        "walk_up": "Move one tile north",
        "walk_down": "Move one tile south",
        "walk_left": "Move one tile west",
        "walk_right": "Move one tile east",
        "press_a": "Interact, confirm, talk, or advance one dialog box",
        "press_b": "Cancel, back out of a menu, or decline",
        "press_start": "Open the main menu",
        "press_select": "Rarely useful; effectively a wasted turn",
        "wait_60": "Do nothing for a moment and let the game animate",
        "hold_a_30": "Hold A through a long unskippable sequence",
        "a_until_dialog_end": "Press A repeatedly until the current dialog finishes",
    }

    def chat(
        self, system: str, user: str, image_b64: str, schema: dict, think: str
    ) -> ChatResult:
        body = self._post(
            self.url,
            {
                "model": self.model,
                # Same information every other seat receives, minus the screenshot it cannot
                # accept. The system prompt carries the rules; `user` carries this turn's state.
                "state": f"{system}\n\n{user}",
                "questions": {
                    "action": {
                        "type": "choice",
                        "instructions": (
                            "Pick the single button action that best makes progress toward the "
                            "current goal. Walking into a wall, tree, or ledge wastes the turn."
                        ),
                        "criteria": dict(self.ACTION_CRITERIA),
                    }
                },
            },
            {"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"},
        )

        answer = (body.get("answers") or {}).get("action") or {}
        usage = body.get("usage") or {}
        tokens = {
            "prompt": int(usage.get("input_tokens", 0)),
            "completion": int(usage.get("output_tokens", 0)),
        }
        choice = answer.get("choice")
        if not isinstance(choice, str) or not choice:
            raise _plan_error("Jev returned no choice", body, tokens)

        # Jev emits no reasoning, so rather than invent one, record what it actually reported:
        # the distribution it chose from. Every character here is lifted from the response.
        probabilities = answer.get("probabilities") or {}
        ranked = sorted(
            ((k, v) for k, v in probabilities.items() if isinstance(v, (int, float))),
            key=lambda kv: -kv[1],
        )[:4]
        spread = " · ".join(f"{name} {value:.2f}" for name, value in ranked)
        confidence = answer.get("confidence")
        thought = f"[no reasoning: System One model] {spread}" if spread else "[no reasoning]"
        if isinstance(confidence, (int, float)):
            thought += f" | confidence {confidence:.2f}"

        return {"thought": thought, "actions": [choice]}, "", tokens


class BedrockProvider(OpenAIProvider):
    """Amazon Bedrock's OpenAI-compatible endpoint, authenticated with a Bedrock API key
    (bearer token, not SigV4). Note this is NOT bedrock-runtime: it is a separate endpoint
    with its own quota allocation, and on a new account bedrock-runtime can sit at zero
    while this one serves fine. Model ids are dotted, e.g. 'qwen.qwen3-vl-235b-a22b-instruct'.
    reasoning_effort is enforced here, but the vision models are -instruct (non-thinking)
    variants, so think=high is accepted and has no effect on them."""

    api_key_env = "AWS_BEARER_TOKEN_BEDROCK"
    base_url = "https://bedrock-mantle.us-west-2.api.aws/v1"


class XAIProvider(OpenAIProvider):
    """xAI's OpenAI-compatible endpoint. grok-4.6 is the vision model, and it takes a PNG data
    URL and a strict json_schema in the SAME request — verified 2026-09-13 against a real
    Pokémon Red frame, which is the one combination xAI's own docs never confirm. Note the
    models page renders every Grok as "Text only"; that column is wrong, the image-understanding
    guide is the primary source. reasoning_effort accepts high/low/minimal but 400s on "none",
    so a row here must not set think: off."""

    api_key_env = "XAI_API_KEY"
    base_url = "https://api.x.ai/v1"

    def _thinking(self, message: dict) -> str:
        """xAI puts it in reasoning_content, not reasoning, so the base returns "" here and
        the run loses the thinking column it records for every other reasoning model."""
        return message.get("reasoning_content") or ""

    def _tokens(self, usage: dict) -> dict[str, int]:
        """xAI reports reasoning OUTSIDE completion_tokens and bills it as output: a turn came
        back with completion_tokens 49 and reasoning_tokens 470, and total_tokens only balances
        when both are counted. Taking completion_tokens alone would understate cost ~10x."""
        details = usage.get("completion_tokens_details") or {}
        return {
            "prompt": int(usage.get("prompt_tokens", 0)),
            "completion": int(usage.get("completion_tokens", 0))
            + int(details.get("reasoning_tokens", 0)),
        }


class DeepSeekProvider(OpenAIProvider):
    """DeepSeek's own endpoint (DEEPSEEK_API_KEY). `deepseek-flash` is V4.1 Flash, the first
    DeepSeek that takes an image natively; the Azure rows above it on the roster discard the
    image and answer blind, which is why this row exists separately.

    Two dialect differences from OpenAI, both handled in _tune_payload: thinking is a
    `thinking: {type: enabled}` switch alongside reasoning_effort, and response_format only
    knows `json_object`, not a strict json_schema. So rows here set `structured_output: false`
    (the schema path would 400) and this class adds json_object on top, which still forces a
    single JSON object while the parse guard checks the shape. Reasoning streams as
    `reasoning_content` deltas and is billed inside completion_tokens, so the default token
    accounting is already right."""

    api_key_env = "DEEPSEEK_API_KEY"
    base_url = "https://api.deepseek.com/v1"

    def _tune_payload(self, payload: dict, effort: str) -> None:
        if "response_format" not in payload:
            payload["response_format"] = {"type": "json_object"}
        if effort in {"", "default"}:
            return
        payload["thinking"] = {"type": "disabled" if effort == "off" else "enabled"}
        if effort == "off":
            payload.pop("reasoning_effort", None)


class AzureOpenAIProvider(OpenAIProvider):
    """Azure OpenAI through the v1 API, which is what makes this a plain subclass: the v1 path
    drops the dated api-version query param and accepts `Authorization: Bearer <key>`, so the
    payload OpenAIProvider already sends works untouched (verified 2026-09-13 with a real frame,
    vision and strict json_schema together). This class is for an Azure OpenAI resource, which
    serves OpenAI-published models only, so the base _tokens is right: gpt-5-mini returned
    prompt 21 + completion 203 == total 224 with reasoning 192 counted INSIDE completion.
    That is a fact about the PUBLISHER, not about Azure — see AzureFoundryProvider, where the
    same wrapper serves xAI models that report reasoning outside it.

    base_url is per-resource, so it comes from the environment rather than a class constant, and
    `model` is the DEPLOYMENT name rather than the model name (they match here by choice)."""

    api_key_env = "AZURE_OPENAI_API_KEY"
    endpoint_env = "AZURE_OPENAI_ENDPOINT"

    def __init__(self, model: str, **opts):
        super().__init__(model, **opts)
        endpoint = os.environ.get(self.endpoint_env, "").strip().rstrip("/")
        if not endpoint:
            raise ValueError(f"{type(self).__name__} requires {self.endpoint_env}")
        self.base_url = f"{endpoint}/openai/v1"


class AzureFoundryProvider(AzureOpenAIProvider):
    """An Azure AI Foundry (AIServices) resource, which serves the whole catalog rather than just
    OpenAI: xAI, MoonshotAI, DeepSeek and Mistral all answer on the same /openai/v1 path. It is a
    different resource from the Azure OpenAI one, with its own endpoint and key, which is why it
    gets its own env pair instead of sharing AZURE_OPENAI_*.

    Its quota is also separate and far easier to get: the OpenAI-published frontier models sat at
    0 TPM and were denied twice, while grok-4.6 was already serving here with no request at all.

    No _thinking override, unlike XAIProvider: Azure returns only ['role', 'content'] for the
    Grok deployments, with neither `reasoning` nor xAI's own `reasoning_content`. The reasoning
    is billed (see _tokens) but its text is not served, so the thinking column stays empty for
    these rows. That is the endpoint's behaviour, not a missing hook."""

    api_key_env = "AZURE_FOUNDRY_API_KEY"
    endpoint_env = "AZURE_FOUNDRY_ENDPOINT"

    def _tokens(self, usage: dict) -> dict[str, int]:
        """Reconcile against total_tokens instead of assuming a publisher, because one endpoint
        serves both conventions and the deployment name does not reliably say which:
            gpt-5-mini  21 + 203           == 224  (reasoning 192 already inside completion)
            grok-4.3   325 + 125 + 1649    == 2099 (reasoning reported alongside it)
        total_tokens is what the bill is built from, so whichever reading reconciles with it is
        the true one. Guessing costs ~8x on the Grok rows.

        Detecting this per response rather than per class matters: grok-4.6 answered one probe
        with reasoning_tokens 0, which balances either way, and an earlier call on that same
        deployment reported 599. A single sample would have picked the wrong rule."""
        prompt = int(usage.get("prompt_tokens", 0))
        completion = int(usage.get("completion_tokens", 0))
        reasoning = int((usage.get("completion_tokens_details") or {}).get("reasoning_tokens", 0))
        # Fall through to OpenAI semantics when total is absent or reconciles with neither.
        if reasoning and int(usage.get("total_tokens", 0)) == prompt + completion + reasoning:
            completion += reasoning
        return {"prompt": prompt, "completion": completion}


def get_provider(provider_name: str, model: str, **opts) -> Provider:
    """Construct an adapter; opts are constructor settings and registry token rates."""
    providers = {
        "ollama": OllamaProvider, "anthropic": AnthropicProvider,
        "openai": OpenAIProvider, "google": GoogleProvider,
        "openrouter": OpenRouterProvider, "jev": JevDecisionProvider,
        "bedrock": BedrockProvider,
        "xai": XAIProvider, "deepseek": DeepSeekProvider, "azure": AzureOpenAIProvider,
        "azure-foundry": AzureFoundryProvider,
    }
    try:
        provider = providers[provider_name.strip().lower()]
    except KeyError:
        raise ValueError(f"Unknown provider {provider_name!r}; choose {', '.join(providers)}") from None
    return provider(model, **opts)
