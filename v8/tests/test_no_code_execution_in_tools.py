"""Rule: MCP tools validate, store, route and signal. They never execute code or commands on the
agent's behalf — the tool tells the agent what to run; the agent runs it in its own shell and
records evidence — and they never swallow failures (every error travels in the envelope).
Standalone process boundaries are explicitly allowlisted: the consultant bridge (consult.py),
the launcher's supervisor (supervisor.py, design §22), and the operator-invoked subscription
collector (usage_sources.py, UI design §4.10). The collector must remain unreachable from
board/tool modules: opening Usage reads receipts and must never launch a provider."""

import pathlib
import re

SRC = pathlib.Path(__file__).resolve().parents[1] / "src" / "edp8"
FORBIDDEN = re.compile(r"(subprocess|os\.system|os\.popen|\bexec\(|\beval\(|(?<!re\.)\bcompile\()")
ALLOWED_SUBPROCESS = {"consult.py", "supervisor.py", "usage_sources.py"}
SILENT = re.compile(r"except\s*(Exception|BaseException)?\s*:\s*\r?\n\s*pass\b")


def test_no_tool_module_executes_code():
    offenders = []
    for f in SRC.glob("*.py"):
        if f.name in ALLOWED_SUBPROCESS:
            continue
        for m in FORBIDDEN.finditer(f.read_text(encoding="utf-8")):
            offenders.append(f"{f.name}: {m.group(0)}")
    assert not offenders, f"tools must not execute code: {offenders}"


def test_operator_usage_collector_is_not_imported_by_runtime_modules():
    # Include all runtime modules, not just the current routers: a future intermediate
    # adapter must not silently make the standalone collector an HTTP/tool side effect.
    offenders = [f.name for f in SRC.glob("*.py")
                 if f.name != "usage_sources.py"
                 and re.search(r"\busage_sources\b", f.read_text(encoding="utf-8"))]
    assert not offenders, f"operator-only collector referenced by runtime: {offenders}"


def test_no_silent_except_pass_in_tool_modules():
    offenders = []
    for name in ("board.py", "bundles.py", "service.py", "client.py", "pool_adapter.py", "mcp_server.py"):
        if SILENT.search((SRC / name).read_text(encoding="utf-8")):
            offenders.append(name)
    assert not offenders, f"silent failure swallowing in: {offenders}"
