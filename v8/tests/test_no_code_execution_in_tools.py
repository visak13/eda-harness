"""Rule: MCP tools validate, store, route and signal. They never execute code or commands on the
agent's behalf — the tool tells the agent what to run; the agent runs it in its own shell and
records evidence — and they never swallow failures (every error travels in the envelope).
The single subprocess is the consultant bridge (consult.py), which surfaces the real exit code
and last error line."""

import pathlib
import re

SRC = pathlib.Path(__file__).resolve().parents[1] / "src" / "edp8"
FORBIDDEN = re.compile(r"(subprocess|os\.system|os\.popen|\bexec\(|\beval\(|(?<!re\.)\bcompile\()")
ALLOWED_SUBPROCESS = {"consult.py"}
SILENT = re.compile(r"except\s*(Exception|BaseException)?\s*:\s*\r?\n\s*pass\b")


def test_no_tool_module_executes_code():
    offenders = []
    for f in SRC.glob("*.py"):
        if f.name in ALLOWED_SUBPROCESS:
            continue
        for m in FORBIDDEN.finditer(f.read_text(encoding="utf-8")):
            offenders.append(f"{f.name}: {m.group(0)}")
    assert not offenders, f"tools must not execute code: {offenders}"


def test_no_silent_except_pass_in_tool_modules():
    offenders = []
    for name in ("board.py", "bundles.py", "service.py", "client.py", "pool_adapter.py", "mcp_server.py"):
        if SILENT.search((SRC / name).read_text(encoding="utf-8")):
            offenders.append(name)
    assert not offenders, f"silent failure swallowing in: {offenders}"
