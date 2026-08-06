# provider-bridge — configuring delegates (v7 WS1)

The bridge (`tools/bridge.py`) runs external models as in-shell tools:
`delegate_generate`, `delegate_review`, `consult_external`,
`adversarial_challenge`. WHO may delegate WHAT is decided twice — by role
(roles.py) and by route (`.bridge.json`) — never by the agent.

## The live delegate: sol (GPT via the Codex subscription)

Configured today in `claude/.bridge.json`:

```json
"sol": {"backend": "cli", "model": "gpt-5.6", "effort": "medium",
        "max_context_tokens": 250000, "max_output_tokens": 16000}
```

`backend: "cli"` runs the Codex CLI through `sol_bridge.py` (binary selection,
argv landmines, no-retry blocker discipline all inherited), ALWAYS read-only —
bridge delegates return text, never write. Billing is the ChatGPT plan quota:
$0 in the audit sidecar, real quota on failure — a non-zero exit is a
first-class blocker, never a retry.

## Adding an HTTP delegate (any OpenAI-compatible provider)

1. Export the provider key in the environment the MCP server inherits, e.g.
   `DEEPSEEK_API_KEY`. The registry stores the env var NAME, never the key.
2. Add the delegate to `claude/.bridge.json`:

```json
"cheap-coder": {
  "backend": "http",
  "model": "<exact pinned model id>",
  "base_url": "https://api.deepseek.com/v1",
  "api_key_env": "DEEPSEEK_API_KEY",
  "effort": "medium",
  "max_context_tokens": 128000,
  "max_output_tokens": 8000,
  "price_in_per_mtok": 0.27,
  "price_out_per_mtok": 1.10
}
```

   Works for OpenAI (`https://api.openai.com/v1`), DeepSeek, Mistral, local
   servers (ollama/vllm with an OpenAI-compat endpoint), and Google via an
   OpenAI-compat gateway. Prices are vendor list, estimation only — they feed
   the audit sidecar (`.bridge/audit-<caller>.jsonl`), which the budget
   machinery reads.

3. Route it. A route is `"role:task_class": "delegate"`; `role:*` is the
   wildcard; NO route = the tool refuses with "do this work yourself":

```json
"routes": {"worker:codegen": "cheap-coder", "worker:tests": "cheap-coder"}
```

4. Validate: `python -m pytest tests/test_bridge.py -q` — the suite parses the
   live `.bridge.json` and fails on a bad entry.

## Rules that never change

- Delegates hold no shell, no MCP, no broker, no write path — one
  request/response inside a tool call.
- Delegated output is an UNTRUSTED DRAFT: the Claude shell owns integration,
  build, tests, and the record. The acceptance gate is why cheap execution is
  safe.
- `adversarial_challenge` output is findings-only DATA (`challenge` broker
  kind), adjudicated through gates — never obeyed.
- Oversized work orders are REFUSED up front (`max_context_tokens`), never
  silently truncated.
