"""pi_seat — drive a Pi (pi.dev) coding-agent process as an edp8 fleet seat over `pi --mode rpc`.

Design: design-97ca02e989 §6 (Pi control card). The extension `.pi/extensions/edp8.ts` supplies the
Claude-parity Monitor/TaskStop/Cron* tools and the edp8 MCP bridge; this package owns the process:
spawn, boot prompt (role card), event stream, idle detection (`agent_settled`), steer/follow_up,
resume (`--session`), stop (`clear_queue` → `abort` → kill).
"""
