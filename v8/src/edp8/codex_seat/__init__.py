"""codex_seat — a GPT-6 Astra fleet seat under `codex app-server` (s-10a2b1f9ec, epic-6a8a6020fd).

The runner (`run.py`) owns one `codex app-server` over stdio JSON-RPC (`rpc.py`) and hosts Claude
Code's Monitor / TaskStop / CronCreate / CronList / CronDelete as the thread's `dynamicTools`
(`tools.py`, a port of `.pi/extensions/edp8.ts` — same schemas, texts, envelopes and delivery rules).
Tool host and delivery engine are one process: a Monitor line or a cron fire becomes `turn/start`
when the thread is idle, attaches to the next seat-tool result or is `turn/steer`ed after the native
tool in flight when busy (architect approval m-c50e181c7f of deviation m-6768770bc5).
"""
