"""Rule: MCP tools validate, store, route and signal. They never execute code or commands on the
agent's behalf — the tool tells the agent what to run; the agent runs it in its own shell and
records evidence — and they never swallow failures (every error travels in the envelope).
Standalone process boundaries are explicitly allowlisted, each with its reason (ALLOWED_SUBPROCESS):
launchers and operator/admin actions, never MCP tools. No MCP tool module may import one of them
(test_mcp_tool_modules_import_no_launcher). The operator-invoked subscription collector
(usage_sources.py, UI design §4.10) must remain unreachable from board/tool modules: opening Usage
reads receipts and must never launch a provider."""

import pathlib
import re

SRC = pathlib.Path(__file__).resolve().parents[1] / "src" / "edp8"
FORBIDDEN = re.compile(r"(subprocess|os\.system|os\.popen|\bexec\(|\beval\(|(?<!re\.)\bcompile\()")
ALLOWED_SUBPROCESS = {
    "supervisor.py": "the launcher's service supervisor (design §22)",
    "usage_sources.py": "the operator-invoked subscription collector (UI design §4.10)",
    "code_service.py": "S21 launcher: `heronry start/stop code` and Admin -> Services start the guard + code-server",
    "update_helper.py": "S3/S21 the detached update helper: install + the compat check, outside the app's tree",
    "desktop.py": "S8 Heronry Desktop: the tray's installer hand-off (runs the downloaded setup exe)",
    "model_catalog.py": "S12 Admin -> Models: reads Codex's model windows (`codex debug models`)",
    "tailnet.py": "S5 Admin -> Remote access: `tailscale status/serve` for an admin's apply/remove",
}
#: the MCP tool layer: registration, tool bodies and their contracts
MCP_TOOL_MODULES = ("mcp_server.py", "bundles.py", "tool_contracts.py", "doc_tools.py", "api_tools.py", "client.py")
SILENT = re.compile(r"except\s*(Exception|BaseException)?\s*:\s*\r?\n\s*pass\b")


def test_no_tool_module_executes_code():
    offenders = []
    for f in SRC.glob("*.py"):
        if f.name in ALLOWED_SUBPROCESS:
            continue
        for m in FORBIDDEN.finditer(f.read_text(encoding="utf-8")):
            offenders.append(f"{f.name}: {m.group(0)}")
    assert not offenders, f"tools must not execute code: {offenders}"


def test_mcp_tool_modules_import_no_launcher():
    # supervisor stays readable from the Help seat's doctor tools (status reads, no launch)
    launchers = [n[:-3] for n in ALLOWED_SUBPROCESS if n != "supervisor.py"]
    offenders = [f"{name}: {mod}" for name in MCP_TOOL_MODULES
                 for mod in launchers
                 if re.search(rf"^\s*(from\s+\S*\b{mod}\b|(from\s+\S+\s+)?import\s+.*\b{mod}\b)",
                              (SRC / name).read_text(encoding="utf-8"), re.M)]
    assert not offenders, f"an MCP tool module imports a process launcher: {offenders}"


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
