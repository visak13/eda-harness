# Running a seat on Pi (any provider, any key)
<!-- roles: owner, architect -->

Pi (pi.dev's coding agent) is the third seat harness next to claude and codex. Use it when you want a
seat on a model neither claude nor codex runs: another vendor's API, a subscription Pi can sign in to,
or a local model. A Pi seat is a normal fleet seat. It boots its role card, calls the edp8 board
through the `.pi/extensions/edp8.ts` extension, and is woken by Monitor lines and cron fires like a
Claude shell.

## 1. Install Pi
- The pool uses its pinned copy at `edp-pool/.pi-harness` when `npm ci` has been run there. Otherwise it
  uses `pi` on PATH (`npm install -g @earendil-works/pi-coding-agent`). `EDP_PI_BIN` overrides both: a
  path to Pi's `cli.js` (run under node) or to a `pi` executable.
- Node is needed only for Pi itself.

## 2. Give Pi a provider and key
Pi resolves credentials per provider. Pick ONE way for each provider:
- **Environment variable** in the pool's environment, for example `ANTHROPIC_API_KEY`, `OPENAI_API_KEY`,
  `GEMINI_API_KEY`, `OPENROUTER_API_KEY`, `MISTRAL_API_KEY`, `GROQ_API_KEY`, `DEEPSEEK_API_KEY` or
  `XAI_API_KEY`. Pi's `docs/providers.md` lists every provider and its variable.
- **Sign-in:** run `pi` once by hand, type `/login` and choose a subscription (ChatGPT Plus/Pro for
  Codex models, Claude Pro/Max, GitHub Copilot, xAI, OpenRouter) or paste an API key. The credential is
  saved in `~/.pi/agent/auth.json` and refreshed automatically.
- **Local or custom endpoint** (Ollama, LM Studio, vLLM, a proxy): declare the provider and its models in
  `~/.pi/agent/models.json` with `baseUrl`, `api` (e.g. `openai-completions`) and `apiKey` (a dummy
  value for a keyless local server). See Pi's `docs/models.md`.

Check it by hand before any spawn: `pi --model <provider>/<model-id>` must answer a prompt.

## 3. Declare the seat in `models.json`
Add a named seat whose `harness` is `pi` and whose `model` is Pi's `<provider>/<model-id>`:

```json
"seats": {
  "my-gemini": {"model": "google/gemini-3-pro", "harness": "pi", "thinking": "medium",
                "context_window": 1000000, "auto_compact": 350000}
}
```

`thinking` is Pi's reasoning level (`low`, `medium` or `high`).

## 4. Use it as a seat
- **One spawn:** `spawn(role=<role>, ticket_id=<ticket>, model="my-gemini")`. The seat name binds the
  model and the thinking level, and the pool routes a `harness: pi` seat to Pi.
- **A whole role:** list the role in `EDP_PI_ROLES` (for example `EDP_PI_ROLES=qa,adversary`) in the
  pool's environment, and name the seat for that role in the `roles_openai` column of `models.json`
  (for example `"qa": "my-gemini"`). An owner restart of the pool applies it.
- **Instead of codex:** when codex is not installed, a Pi seat on `openai-codex/<id>` (ChatGPT sign-in)
  or `openai/<id>` (`OPENAI_API_KEY`) runs the same GPT models. The adversary role still needs its own
  choice: with codex not selected it defaults to Fable (`claude-fable-5-1`), with the risk notice.

## 5. What to expect
- The pool opens Pi's interactive TUI in its own console (monitor mode), or runs it headless over RPC.
  Either way the seat's identity reaches the board as headers from its environment, never on argv.
- Pi seats share the OpenAI inference lane (`admission.py`) with codex seats, so turns on one login queue
  instead of colliding.
- A model that does not follow tool-calling instructions well makes a poor seat. Try it on a small task
  ticket first.
