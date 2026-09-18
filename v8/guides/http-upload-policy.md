# Opt-in SINGLE-HOST HTTP file uploads

This is an explicit capability for trusted co-hosted board/MCP/seat processes, **off by default**.
It does not enable remote arbitrary-host file reads. Pi still uses its local adapter unchanged.
Local stdio still uses an operator-supplied EDP8_UPLOAD_ROOT. No extra MCP process per Claude
seat is required for this shared HTTP policy.

## Operator configuration (not tool arguments)
Set only in the MCP server's deployment environment, then activate through owner maintenance:

```
EDP8_HTTP_UPLOAD_MODE=single-host
EDP8_HTTP_UPLOAD_POLICY=C:\operator-config\http-upload-policy.json
EDP8_MCP_HOST=127.0.0.1
EDP8_BOARD_URL=http://127.0.0.1:9400
```

Example JSON (replace with actual canonical existing paths and canonical participant IDs):

```json
{
  "version": 1,
  "workspace_root": "C:\\Projects\\board-workspace",
  "seats": {
    "engineer.s-example": {"scratch_root": "C:\\seat-scratch\\engineer.s-example"},
    "architect.epic-example": {}
  }
}
```

Every enrolled participant may upload from the shared workspace and only its own optional scratch
root. Roots must be absolute, already canonical, existing local directories (no Windows UNC/device
roots). Filesystem roots, the user's
whole home or whole Temp (and ancestors of those) are forbidden. Scratch roots cannot overlap each
other or the workspace (otherwise per-seat isolation is fictitious). Policy must reside outside all
allowed roots, with operator-only write ACLs. The operator must choose a workspace containing only
files these enrolled seats are authorized to share: this feature is not a sandbox against seats that
already have unrestricted shell access. Do not enroll an untrusted participant in a shared secret
workspace. ACL provisioning and policy editing are operator actions, not model tool parameters.

Policy reads at MCP startup, at most 64KB. Missing/malformed/invalid config disables the route.
Anything other than exact mode `single-host` disables it. Public URL configuration, non-loopback MCP
bind or board URL disables it. Requests must originate from a loopback transport peer, without
Forwarded/X-Forwarded-For/X-Real-IP headers. Do not expose this listener through proxies/tunnels; an
opaque tunnel without forwarding metadata cannot be reliably detected, and is outside the opt-in
single-host deployment contract. Loopback is an additional boundary, never authentication.

## Authentication and path boundary
1. Missing request X-Token is denied, never replaced by the proxy's environment token.
2. POST /v1/artifacts/upload-authorize checks the same board participant/token registry as normal
   requests **and requires a configured nonempty matching token even in legacy trusted mode**.
   Identity in X-Participant alone never authorizes a server file read.
3. Canonical returned participant ID must be enrolled in operator policy. Model-supplied roots are
   neither accepted nor used. Unknown/unenrolled/incorrect-token calls fail before requested-file I/O.
4. HTTP path must be absolute, without `..`, lexically beneath an enrolled root. Existing local
   stream then verifies canonical containment AND actual opened-handle containment against the
   startup-pinned root (never re-resolved to follow a later root junction substitution; Windows
   GetFinalPathNameByHandleW / Linux proc fd), regular-file type and 25MB limit. Junction/symlink
   escape and alternate data streams are refused; file growth during streaming remains capped.
5. Multipart is sent with the same request seat credentials. Existing board sniffed MIME rules,
   staged ownership and message_send(artifacts=[id]) finalization remain authoritative. The artifact's
   created_by is the authenticated caller. No base64/file body or credential enters tool receipts.

Errors are typed envelopes, with no file contents or credentials. Disabled/unconfigured/remote,
unauthenticated and unenrolled requests do not resolve/open the requested file. A failed upload may
leave an existing-style staged record if the reply is lost; do not assert attachment success until
message_send/read confirm it. The policy is process-local immutable configuration; changing the file
alone does not hotload it or change active sessions.

## Activation and rollback
No live configuration is performed by tests or this change. Owner names exact board/MCP maintenance,
coordinates seat refresh, and protects/provisions config and existing seat tokens. Deploy board auth
endpoint and MCP policy together; old board missing the endpoint fails closed. Verify new tools/list,
then use a disposable configured workspace file and isolated ticket to verify upload→attach. Keep
remote/public environments disabled. Rollback/remove the opt-in and restart only through owner
maintenance; existing artifact/doc/audit records remain readable. Never change currently loaded
session cron to call a new tool before its schema is confirmed available.

Cold proof: `.venv/Scripts/python.exe -m pytest tests/test_http_upload_policy_s7.py -q`.
This uses only temporary operator config, in-memory board and owned free-port HTTP fixtures.
