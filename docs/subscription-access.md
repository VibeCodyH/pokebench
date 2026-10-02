# Subscription inference in PokéBench

This changes the credentials and request format used by one provider. PokéBench still
owns the prompt, screenshots, history, plan schema, action validation, and turn budget.
It does not launch Codex, Claude Code, Gemini CLI, or another agent loop.

## ChatGPT setup

Status: local ChatGPT sign-in and catalog access verified on 2026-10-02. A live
`gpt-5.6-terra` screenshot/schema smoke passed at `high` reasoning in 3.679 seconds,
with 1,046 input and 78 output tokens. The subscription model row is
`chatgpt-gpt-5.6-terra`, with the same 131,072-token history budget as Sol and Luna.
No scored game was started and no live server was deployed or restarted.
The credential-free [smoke receipt](validation/terra-subscription-smoke-2026-10-02.json)
is committed with the adapter so the measurements survive a new checkout.

The smoke returned a valid `wait_60` plan, but called the visible trainer sprite
Professor Oak. This verifies the transport and response contract, not visual accuracy
or gameplay quality. Image input accounted for 32 tokens in the provider's attribution.
The first two requests exposed a parser bug: this route's terminal completion event
can have an empty output snapshot. The adapter now retains completed output-item
events while still requiring final completion and usage before accepting a plan.

Offline validation: 128 tests passed on 2026-10-02, including OAuth identity/state/scope
checks, rotating credentials, exact request content, stream failures, quota handling,
and subscription receipts. To include these tests, install `requirements-oauth.txt`
alongside the normal test dependencies, then run `python -m unittest discover -s tests`.
Offline tests alone do not establish account eligibility; the separate live smoke
above verifies this account and Terra at the recorded time, not sustained run quota.

OpenAI documents direct subscription-funded Responses requests for open-source/local
clients. PokéBench registers under its own name using dynamic registration and PKCE.
It does not import another tool's client ID or credentials. Sources checked 2026-10-02:
[registration](https://developers.openai.com/siwc/token-sharing-open-source/sign-in),
[inference](https://developers.openai.com/siwc/token-sharing-open-source/models-and-inference),
[preview limits](https://developers.openai.com/siwc/token-sharing-open-source/preview-limitations).

1. Install the optional login verifier into the existing Python environment:

   ```sh
   .venv/bin/python -m pip install -r requirements-oauth.txt
   ```

2. Sign in and authorize PokéBench's access to your ChatGPT plan:

   ```sh
   .venv/bin/python chatgpt_auth.py login
   ```

   Credentials are stored outside the repository in
   `~/.config/pokebench/chatgpt/default.json`, with owner-only file permissions.
   The runtime keeps one stable host identifier. Rotating refresh tokens are updated
   atomically under a per-profile file lock. Account tokens are never printed.
   `--profile NAME` before the subcommand selects a separate account/workspace registration;
   `POKEBENCH_CHATGPT_PROFILE=NAME` selects it in the benchmark runner.
   `POKEBENCH_CHATGPT_AUTH_DIR` can select private persistent runtime storage.
   Do not set that directory inside a tracked repository.

   On a remote host, use `login --no-browser --port 1455` and forward local port 1455
   to that host before opening the printed URL. Keep the auth store on the host that
   actually runs inference. Do not copy one live refresh-token store to multiple hosts.

3. In [ChatGPT Usage settings](https://chatgpt.com/settings/usage), set PokéBench's plan
   allowance and disable using purchased credits after its subscription limit, if that
   option is present. The adapter never falls back to `OPENAI_API_KEY`; provider-side
   credit permissions are controlled by those account settings.

4. Read the account's real catalog, then probe an exact returned model with a PNG:

   ```sh
   .venv/bin/python chatgpt_auth.py models
   .venv/bin/python chatgpt_auth.py probe --model gpt-5.6-terra --display-name 'GPT 5.6 Terra' --think high --image /path/to/frame.png
   ```

   The probe makes one real subscription inference call and prints its plan and token
   counts. It does not start a game, press buttons, or publish a score. Use the model's
   documented reasoning level; a rejected level or schema is a failed preflight, not
   permission to silently drop either. Check that the description matches the image.

5. Only after the probe passes, add a normal `models.yaml` row with `provider: chatgpt`,
   the verified `api_model_id`, the correct identity/family, context and reasoning
   settings, and both per-token prices `null`. Do not set `max_output_tokens`: this
   route does not support it. Continue using the normal runner and recording workflow.

The Responses route receives the exact harness system text as `instructions`, the
exact user/history text and PNG as one user input, and the existing strict plan schema.
No tools, persistent conversation, extra memories, web search or agent instructions
are included. `store: false` and `stream: true` are required by this route. Temperature
is omitted, as with the existing OpenAI adapter. History stays entirely with PokéBench.

A plan is accepted only after `response.completed`, with valid usage and a served-model
identifier. Partial streams, refusals, unexpected tool output and missing usage fail
the turn. A changed served-model identifier or exhausted subscription stops the run
as `provider_error`; no scored result is produced. Temporary failures use the existing
bounded runner retries. The existing time and output-volume guards still apply.

Receipts record `execution_route: openai-chatgpt-subscription`,
`billing_mode: subscription`, `served_model`, token usage and `cost_usd: null`.
Null means the subscription cost has not been allocated to a run, not free inference.
The prompt hash is unchanged. The two new adapter/auth files enter the harness file hash.

To disconnect, remove PokéBench in ChatGPT Settings. A terminal refresh-token error
clears unusable local tokens while retaining the account/client mapping for sign-in.

## Preparing a full recorded run

The smoke does not start an emulator or publish a score. Before the first full run:

1. Deploy the committed adapter and registry to the selected runtime. Verify that it
   has `chatgpt_auth.py`, `chatgpt_provider.py`, `providers.py`, `run_benchmark.py`,
   `qwen_red.py`, `milestones.py`, `serve_live.py`, and `models.yaml` from the intended
   revision. The current `docker/Dockerfile` predates the registry runner and copies
   only the original server files; rebuilding it unchanged does not deploy this route.
2. Install `requirements-oauth.txt` where sign-in runs and configure private,
   persistent credential storage. A desktop sign-in does not authorize a different
   runtime automatically. Register that runtime with its own stable host ID and use
   the loopback/port-forward flow above. Do not clone a live rotating credential store.
3. Recheck the account catalog, plan allowance/credit-overflow settings, and one PNG
   request on the actual runtime. Keep `high` reasoning, the strict schema, and the
   registry's 131,072-token history budget. Sustained quota is still unmeasured.
4. Check host-side runner processes and coordinate an idle server before any deploy,
   reset, or restart. Restarting a shared game-server container kills its active run.
   Start and verify the existing recorder/watcher workflow before the fresh game.
5. Launch `run_benchmark.py` with `--model-key chatgpt-gpt-5.6-terra --turns 1000`,
   the verified idle server URL, and a unique run name. Keep frame capture enabled.
   Record the actual commit/file hashes, subscription route, served model and usage.
   Confirm the opening turns, recording, and host-side watcher remain healthy.

Quota exhaustion stops as `provider_error`, with no API-key fallback or scored result.
The adapter cannot allocate a per-run share of the subscription price; keep USD cost
null. Use the normal completed-run validation and recording workflow before publishing
anything to the leaderboard.

## Other subscriptions: purchasing research, 2026-10-02

Direct API access can use either OAuth or a subscription-specific API key. Neither
requires an extra agent harness. A coding plan with an endpoint is not automatically
permission to run an unattended game benchmark, and a plan may expose only a current
alias rather than every historical model.

| Provider | Finding for this benchmark | Source |
| --- | --- | --- |
| OpenAI | Documented direct subscription inference. Account admission, exact models, vision/schema and quota still require testing. | [OpenAI](https://developers.openai.com/siwc/token-sharing-open-source) |
| Claude | Subscription OAuth is for native Anthropic applications. Custom products are directed to API billing. Calling the unmodified Claude Code binary retains a second harness. | [Anthropic](https://code.claude.com/docs/en/legal-and-compliance#authentication-and-credential-use) |
| Google | Google AI Pro/Ultra applies to Gemini CLI sign-in. A supported direct subscription-inference integration for PokéBench was not established. Do not assume a normal Gemini API key uses the subscription. | [Gemini CLI](https://geminicli.com/docs/get-started/authentication/) |
| Meta Muse Code | Subscription credential is explicitly for Muse Code CLI only. Additional Meta API keys are pay-as-you-go. | [Meta](https://dev.meta.ai/help/subscriptions/what-is-a-muse-code-subscription) |
| Moonshot/Kimi | Has a subscription API and third-party integrations, but explicitly restricts subscriptions to personal interactive use and prohibits non-interactive automation. That conflicts with unattended benchmark runs. Also verify model identity: some docs use a rolling `kimi-for-coding` alias. | [Guidelines](https://www.kimi.com/code/docs/en/kimi-code/community-guidelines.html), [API](https://www.kimi.com/code/docs/en/) |
| xAI/Grok | Hermes' own integration docs demonstrate subscription OAuth to xAI Responses. They also report active standard SuperGrok accounts receiving 403. This is implementation evidence, not xAI approval or proof PokéBench can register its own client. Do not buy a subscription on this evidence alone. | [Hermes implementation guide](https://github.com/NousResearch/hermes-agent/blob/main/website/docs/guides/xai-grok-oauth.md) |
| Mistral | Current subscription docs explicitly share included monthly usage across Studio, API and Vibe Code. Ordinary API requests can preserve the harness. Disable pay-as-you-go overflow. Check plan credits and vision-model catalog before purchase. | [Mistral](https://docs.mistral.ai/admin/billing-usage/subscriptions), [pricing](https://mistral.ai/pricing/) |
| Ollama Cloud | Direct API hosting with subscription credits; current Pro advertises $20/month with $60 in monthly usage credits. This is a credit discount, not unlimited models. Check each model's vision support and serving format. | [Pricing](https://ollama.com/pricing), [cloud API](https://docs.ollama.com/cloud) |
| MiniMax | Subscription keys work with direct compatible APIs, including multimodal capabilities. However the FAQ calls the plan individual interactive developer use. Benchmark permission remains unclear; confirm that before buying for unattended runs. Five-hour and weekly windows apply. | [Integrations](https://platform.minimax.io/docs/token-plan/other-tools), [limits](https://platform.minimax.io/docs/token-plan/faq) |
| Z.ai | Coding Plan is restricted to officially supported tools/products and listed models; no supported PokéBench direct route established. | [FAQ](https://docs.z.ai/devpack/faq) |
| Alibaba/Qwen coding plans | Explicitly prohibit automated scripts, custom application backends and non-interactive calls. Not suitable for this runner. | [FAQ](https://www.alibabacloud.com/help/en/model-studio/coding-plan-faq) |

Pricing and access can change. Do not extrapolate completed runs from advertised prompt
counts: long context and reasoning can consume much more quota per request. Verify
vision, structured output, the model actually served and token usage on a real PNG before
adding any provider to the benchmark. Never spoof another tool's identity to gain access.
