# Agent tool workflows

Discover names with `describe_objects()`; `describe(type=...)` remains compatible. Discovery
links schemas, relationships and skills rather than embedding their manuals. `describe('enums')`
lists fixed domains. IDs, scope names, tags, models and free text stay dynamic.

For documents: doc_create → link_create → doc_read → doc_edit(id, expected_version, edits).
Every old_text is matched uniquely against the ORIGINAL current body; overlaps or missing /
ambiguous matches and stale versions write nothing. One success creates one version and a
compact receipt. Existing doc_update keeps full output unless compact=true. Request
`doc_read(limit=8192)` for bounded character ranges; follow the returned continuation exactly,
including version. Section is a unique exact Markdown heading line, offsets section-relative.
Without range arguments doc_read keeps the old full-body default. Related skills: methodology,
verify, handoff.

For files: artifact_upload(path, note) → message_send(artifacts=[id], ...). Upload is staged
until the message finalizes it. The caller owns the upload; existing MIME sniffing/25 MB/auth
rules remain. Never paste image base64 into a model tool argument. Related skill: demo.

## Explicit review handoff
Evidence refs may describe incomplete or failed work. Attaching them, editing a doc, or posting
a status/note never moves ready/in_progress work into review. After verification and the final
consult result, the assignee deliberately calls `ticket_update(status='in_review')`; all criteria
still need evidence. The transition remains permission-checked/audited and waits for an in-flight
consult. Passing checker verdicts after this handoff still complete work automatically, and
parent/dependency/gate/acceptance/single-QA automation remains active. Returning work to
in_progress requires a new explicit handoff even when old evidence refs remain.

## Transport matrix
- Pi extension: local interception uses per-call trusted ctx.cwd and the installed Python helper;
  bounded multipart directly to the board with seat credentials. No proxy path reads.
- Seat-local stdio MCP: operator explicitly sets EDP8_UPLOAD_ROOT; same handle-verified boundary.
- Shared HTTP MCP: default typed unavailable. Operator may explicitly enable the single-host
  authenticated policy in `guides/http-upload-policy.md`; it supports Claude HTTP clients without
  a per-seat MCP process. No root inferred from proxy cwd or caller-provided headers. Remote or
  proxied deployments remain unsupported and fail closed.

Activation requires owner-coordinated board/MCP deployment and new/reloaded Pi sessions. This
code does not reload services, edit live crons or change active CLI configuration. Old clients
remain compatible. Rollback scoped tool/adapter code together; existing doc versions and
artifact records stay readable. A lost upload response may leave a staged file; do not blindly
claim attachment success (existing staging sweep handles abandoned uploads).

## Fixed-domain audit
Tool enums: roles; ticket kind/work type/status; criterion check/checker/verdict; doc type;
link relation; message kind; status result; gate; artifact form; consult purpose/profile/model;
spawn effort (low/medium/high), mode (headless/monitor), session state. Boolean switches and
bounded numeric ranges remain their native schema types. No fixed string domain remains
in single-choice arguments. describe type is an extensible object/enum registry name; get_guide
name is a file-backed registry. ticket_read include and find types are legacy comma-separated
projections, not single choices: retaining their string contracts avoids breaking existing
clients. Arbitrary IDs, URIs, model registry names, scope, text, tags, recipients, filters and
paths must never be narrowed to fabricated enums.
