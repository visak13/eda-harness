# Spawned-shell telemetry (OpenTelemetry → Phoenix)

Every shell the pool spawns (planner / worker / curiosity / …) is a
`claude` process that exports its OWN OpenTelemetry trace tree — so a
token burn is **measured, not guessed**. Wired in
`edp-pool/.../pty_launcher.py::build_env` (`_shell_otel_env`).

## What you get

The trace-beta span tree per turn, with per-request token counts:

```
claude_code.interaction               (one per turn)
├── claude_code.llm_request           (input_tokens, output_tokens,
│                                       cache_read_tokens, cache_creation_tokens)
└── claude_code.tool
    ├── claude_code.tool.blocked_on_user
    └── claude_code.tool.execution
```

So you can see exactly which turns/tools burned tokens (e.g. a
misread-and-discarded plan vs. guide loading).

## How it's wired

`build_env` does `os.environ.copy()` then, gated by `EDP_SHELL_OTEL`
(default **on**), sets (each value overridable):

| var | default | meaning |
|---|---|---|
| `CLAUDE_CODE_ENABLE_TELEMETRY` | `1` | enable export |
| `CLAUDE_CODE_ENHANCED_TELEMETRY_BETA` | `1` | the span tree (per-request tokens) |
| `OTEL_TRACES_EXPORTER` | `otlp` | |
| `OTEL_METRICS_EXPORTER` / `OTEL_LOGS_EXPORTER` | `none` | Phoenix is traces-only |
| `OTEL_EXPORTER_OTLP_PROTOCOL` | `http/protobuf` | |
| `OTEL_EXPORTER_OTLP_TRACES_ENDPOINT` | `http://localhost:6006/v1/traces` | Phoenix collector |
| `OTEL_RESOURCE_ATTRIBUTES` | per-shell | `service.name=edp-<role>, edp.role, edp.handle, edp.recipe_id` |

Disable entirely: `EDP_SHELL_OTEL=0`. Redirect to a different collector:
set `OTEL_EXPORTER_OTLP_TRACES_ENDPOINT` in the pool's environment (it
wins over the default).

## Correlation note (interactive shells)

All agent shells run as **interactive PTYs**, and Claude Code
deliberately ignores inbound `TRACEPARENT` in interactive mode — so a
planner's spans do NOT auto-nest under the neuron's. Each shell is its
own trace root. To see a recipe's whole fleet together, **group by the
`edp.recipe_id` resource attribute** in Phoenix (the pool derives it from
each shell's handle). `edp.role` and `edp.handle` further distinguish
shells. This is correlation-by-attribute in place of trace-nesting; it's
the price of interactive shells and is sufficient for per-shell and
per-recipe token analysis.

## Deeper debugging (optional, privacy-heavy)

To see the actual prompt/context content burning tokens, set
`OTEL_LOG_RAW_API_BODIES=file:<dir>` in the pool env — it dumps the full
Messages API request/response JSON (entire conversation history) per
request. Local debugging only.
