"""Direct Responses inference funded by ChatGPT, with no external agent harness."""
import json
import time

import requests

from chatgpt_auth import Credentials, RESOURCE
from providers import Provider, _call_expired, _plan_error, _plan_with_usage, _schema_for, _stream_overrun


class ChatGPTProvider(Provider):
    route = "openai-chatgpt-subscription"
    billing_mode = "subscription"

    def __init__(self, model, *, max_tokens=None, structured_output=True, profile=None, **opts):
        super().__init__(model, **opts)
        if max_tokens is not None:
            raise ValueError("ChatGPT plan inference does not support max_output_tokens")
        if self.input_cost_per_mtok is not None or self.output_cost_per_mtok is not None:
            raise ValueError("ChatGPT subscription rows must use null per-token prices")
        self.max_tokens = None
        self.structured_output = structured_output
        self.credentials = Credentials(profile)
        if not self.credentials.read().get("access_token"):
            raise ValueError("Sign in first: python chatgpt_auth.py login")
        self.served_model = None

    def chat(self, system, user, image_b64, schema, think):
        payload = {
            "model": self.model,
            "instructions": system,
            "input": [{"role": "user", "content": [
                {"type": "input_text", "text": user},
                {"type": "input_image", "image_url": f"data:image/png;base64,{image_b64}"},
            ]}],
            "store": False, "stream": True,
        }
        if self.structured_output:
            payload["text"] = {"format": {
                "type": "json_schema", "name": "game_plan", "strict": True,
                "schema": _schema_for(schema, "openai"),
            }}
        effort = think.strip().lower()
        if effort not in {"", "default"}:
            payload["reasoning"] = {"effort": "none" if effort == "off" else effort}
        # No tools, session continuation, extra instructions, or paid-key fallback.
        token = self.credentials.access_token()
        completed = self._responses(payload, token)
        usage = completed.get("usage") or {}
        if any(type(usage.get(k)) is not int or usage[k] < 0
               for k in ("input_tokens", "output_tokens")):
            raise ValueError("ChatGPT completed without valid token usage")
        tokens = {"prompt": usage["input_tokens"], "completion": usage["output_tokens"]}
        model = completed.get("model")
        if not isinstance(model, str) or not model:
            raise _plan_error("ChatGPT omitted the served model", "", tokens)
        if self.served_model and self.served_model != model:
            error = _plan_error("ChatGPT changed the served model during the run", "", tokens)
            error.non_retryable = True
            raise error
        self.served_model = model
        content, reasoning = [], []
        output = completed.get("output", [])
        # GPT-5.5 can send a `commentary` message before the `final_answer` one, often with the
        # same text. Only the final answer is the plan; joining both doubles the JSON.
        final_only = any(item.get("type") == "message" and item.get("phase") == "final_answer"
                         for item in output)
        for item in output:
            if item.get("type") == "reasoning":
                reasoning.extend(part.get("text", "") for part in item.get("summary", []))
            elif item.get("type") == "message":
                if final_only and item.get("phase") != "final_answer":
                    continue
                for part in item.get("content", []):
                    if part.get("type") == "refusal":
                        raise _plan_error("ChatGPT refused the plan", part.get("refusal"), tokens)
                    if part.get("type") == "output_text":
                        content.append(part["text"])
            else:
                raise _plan_error("ChatGPT returned an unexpected output/tool item", "", tokens)
        text = "".join(content)
        if not self.structured_output:
            from qwen_red import _extract_json
            text = _extract_json(text)
        return _plan_with_usage(text, tokens), "".join(reasoning), tokens

    def _responses(self, payload, token):
        deadline = time.monotonic() + self.max_call_s
        response = requests.post(RESOURCE + "/responses", json=payload, headers={
            "Authorization": "Bearer " + token, "Content-Type": "application/json",
        }, timeout=self.timeout, stream=True)
        delivered = 0
        data_lines = []
        output_items = {}
        try:
            if not response.ok:
                response.content
                try:
                    code = response.json().get("error", {}).get("code")
                except (ValueError, AttributeError):
                    code = None
                if response.status_code == 400 or code in {"subscription_sharing_usage_limit_exceeded",
                                                           "subscription_sharing_unsupported_capability"}:
                    error = requests.HTTPError(f"ChatGPT: {code}", response=response)
                    error.non_retryable = True
                    raise error
                response.raise_for_status()
            response.encoding = "utf-8"
            for line in response.iter_lines(decode_unicode=True, delimiter="\n"):
                if time.monotonic() > deadline:
                    raise _call_expired(self.max_call_s, "", "")
                line = line.rstrip("\r")
                if line.startswith("data:"):
                    data_lines.append(line[5:].lstrip())
                    if sum(map(len, data_lines)) > self.max_call_chars * 4:
                        raise _stream_overrun(self.max_call_chars, self.max_call_chars + 1, "", "")
                    continue
                if line or not data_lines:
                    continue
                frame = json.loads("\n".join(data_lines))
                data_lines = []
                event = frame.get("type", "")
                if event == "response.output_item.done":
                    index, item = frame.get("output_index"), frame.get("item")
                    if type(index) is not int or index < 0 or not isinstance(item, dict):
                        raise ValueError("ChatGPT returned an invalid completed output item")
                    output_items[index] = item
                    if sum(len(json.dumps(value)) for value in output_items.values()) > self.max_call_chars * 4:
                        raise _stream_overrun(self.max_call_chars, self.max_call_chars + 1, "", "")
                delta = frame.get("delta")
                if isinstance(delta, str):
                    delivered += len(delta)
                    if delivered > self.max_call_chars:
                        raise _stream_overrun(self.max_call_chars, delivered, "", "")
                if event in {"response.failed", "error"}:
                    body = frame.get("response") or frame
                    detail = body.get("error") or body
                    if not isinstance(detail, dict):
                        detail = {"message": str(detail)}
                    code = detail.get("code", "response_failed")
                    failure = requests.Response()
                    failure.status_code = {
                        "subscription_sharing_usage_limit_exceeded": 429,
                        "subscription_sharing_user_not_eligible": 403,
                        "subscription_sharing_route_not_supported": 403,
                        "subscription_sharing_invalid_user": 401,
                        "chatpass_v2_scope_not_authorized": 403,
                        "chatpass_v2_invalid_authorization_context": 403,
                        "subscription_sharing_unsupported_capability": 400,
                    }.get(code, 503)
                    failure._content = json.dumps({"error": detail}).encode()
                    error = requests.HTTPError(f"ChatGPT: {code}", response=failure)
                    error.non_retryable = failure.status_code in {400, 401, 403, 429}
                    raise error
                if event == "response.incomplete":
                    raise ValueError("ChatGPT response was incomplete; no action accepted")
                if event == "response.completed":
                    completed = frame.get("response") or {}
                    if completed.get("status") != "completed":
                        raise ValueError("ChatGPT completion event has an invalid status")
                    # The subscription route can omit the final output snapshot. Its completed
                    # items arrive earlier; deltas alone are never accepted as a completed plan.
                    if not completed.get("output") and output_items:
                        if sorted(output_items) != list(range(len(output_items))):
                            raise ValueError("ChatGPT stream is missing completed output items")
                        completed["output"] = [output_items[i] for i in sorted(output_items)]
                    # Apply the same output-volume limit if the endpoint omitted delta events.
                    text_size = sum(len(part.get("text", ""))
                                    for item in completed.get("output", [])
                                    for part in item.get("content", []) + item.get("summary", []))
                    if text_size > self.max_call_chars:
                        raise _stream_overrun(self.max_call_chars, text_size, "", "")
                    return completed
            raise ValueError("ChatGPT stream ended without response.completed; no action accepted")
        finally:
            response.close()
