# Launch the base /neuron session WITH OpenTelemetry → Phoenix.
#
# The neuron is launched by YOU via the npm `claude` CLI, NOT by the pool,
# so it never goes through the pool's build_env — it has no telemetry env
# of its own. Run THIS instead of bare `claude` to give the neuron the
# same tracing the spawned agents get (its spans land in the `edp-shells`
# Phoenix project, tagged edp.role=neuron). Spawned planners/workers are
# handled automatically by the pool; this is only for the base session.
#
# Usage (from the claude repo dir):
#   .\scripts\claude-neuron.ps1                 # then type /neuron <goal>
#   .\scripts\claude-neuron.ps1 /neuron "..."   # args pass through to claude
#
# Every value falls back to a sensible default but honors a pre-set env
# var, so you can point at a different collector without editing this file.

if (-not $env:CLAUDE_CODE_ENABLE_TELEMETRY)        { $env:CLAUDE_CODE_ENABLE_TELEMETRY = "1" }
if (-not $env:CLAUDE_CODE_ENHANCED_TELEMETRY_BETA) { $env:CLAUDE_CODE_ENHANCED_TELEMETRY_BETA = "1" }
if (-not $env:OTEL_TRACES_EXPORTER)                { $env:OTEL_TRACES_EXPORTER = "otlp" }
if (-not $env:OTEL_METRICS_EXPORTER)               { $env:OTEL_METRICS_EXPORTER = "none" }
if (-not $env:OTEL_LOGS_EXPORTER)                  { $env:OTEL_LOGS_EXPORTER = "none" }
if (-not $env:OTEL_EXPORTER_OTLP_PROTOCOL)         { $env:OTEL_EXPORTER_OTLP_PROTOCOL = "http/protobuf" }
if (-not $env:OTEL_EXPORTER_OTLP_TRACES_ENDPOINT)  { $env:OTEL_EXPORTER_OTLP_TRACES_ENDPOINT = "http://localhost:6006/v1/traces" }
if (-not $env:OTEL_RESOURCE_ATTRIBUTES)            { $env:OTEL_RESOURCE_ATTRIBUTES = "openinference.project.name=edp-shells,edp.role=neuron" }

claude @args
