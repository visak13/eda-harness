"""Rule: MCP tools validate, store, route and signal. They never execute code or commands on the
agent's behalf — the tool tells the agent what to run; the agent runs it in its own shell and
records evidence — and they never swallow failures (every error travels in the envelope).
Standalone process boundaries are explicitly allowlisted, each with its reason (ALLOWED_SUBPROCESS):
launchers and operator/admin actions, never MCP tools. No MCP tool module may import one of them
(test_mcp_tool_modules_import_no_launcher), except the named pairs in TOOL_LAUNCH_EXCEPTIONS: the MCP server
imports browser_proxy, the one shared headless browser service (t-732cf1dd92, owner ruling), whose argv is
browser_tool.service_argv(port, out), fixed and pinned, and which no tool input reaches
(test_browser_tool_input_never_reaches_the_service_argv). The operator-invoked subscription collector
(usage_sources.py, UI design §4.10) must remain unreachable from board/tool modules: opening Usage
reads receipts and must never launch a provider."""

import json
import pathlib
import re

import httpx

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
    "pain_git.py": "e0cec S6: read-only `git merge-base --is-ancestor <sha> main`, so an architect's `fixed` pain names a merged commit",
}
_BROWSER_SERVICE = ("t-732cf1dd92 (owner ruling): the one shared headless browser service; its argv is "
                    "browser_tool.service_argv(port, out), fixed and pinned, and no tool input reaches it")
ALLOWED_SUBPROCESS["browser_proxy.py"] = _BROWSER_SERVICE
#: (MCP tool module, launcher) pairs the import rule allows, each with its reason; nothing else is skipped
TOOL_LAUNCH_EXCEPTIONS = {("mcp_server.py", "browser_proxy"): _BROWSER_SERVICE}
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
                 if (name, mod) not in TOOL_LAUNCH_EXCEPTIONS
                 and re.search(rf"^\s*(from\s+\S*\b{mod}\b|(from\s+\S+\s+)?import\s+.*\b{mod}\b)",
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


def test_browser_tool_input_never_reaches_the_service_argv(monkeypatch, tmp_path):
    # the browser_proxy exception holds only while the spawned argv is service_argv(port, out) and nothing else
    from edp_contracts import browser_tool
    from edp8 import browser_proxy as bp

    hostile = "--remote-debugging-port=1 & calc.exe ; $(rm -rf ~) --user-data-dir=C:/pwn"
    spawned: list[list[str]] = []

    class Proc:
        pid, returncode = 4242, None

        def poll(self):
            return None

    def fake_popen(argv, **kw):
        spawned.append(list(argv))
        return Proc()

    monkeypatch.delenv("EDP_BROWSER_MCP_PORT", raising=False)
    monkeypatch.setattr(bp, "popen_service", fake_popen)
    monkeypatch.setattr(bp, "_free_port", lambda: 45678)
    monkeypatch.setattr(bp.socket, "create_connection", lambda *a, **k: type("C", (), {"close": lambda self: None})())
    monkeypatch.setattr(bp.settings, "logs_dir", lambda: tmp_path / "logs")
    monkeypatch.setattr(browser_tool, "install_dir", lambda: tmp_path / "browser-mcp")
    monkeypatch.setattr(browser_tool, "ensure_installed", lambda **k: {"browser": "chromium"})
    monkeypatch.setattr(browser_tool, "require_tool", lambda name, **k: f"/bin/{name}")

    seen: list[dict] = []

    def upstream(req: httpx.Request) -> httpx.Response:
        body = json.loads(req.content)
        if body["method"] == "initialize":
            return httpx.Response(200, headers={"content-type": "application/json", "mcp-session-id": "up-1"},
                                  json={"jsonrpc": "2.0", "id": body["id"], "result": {}})
        if "id" not in body:
            return httpx.Response(202)
        seen.append(body["params"])
        return httpx.Response(200, json={"jsonrpc": "2.0", "id": body["id"],
                                         "result": {"content": [{"type": "text", "text": "ok"}]}})

    proxy = bp.BrowserProxy(bp.Service(), origins=frozenset({"http://127.0.0.1:1"}),
                            http=httpx.Client(transport=httpx.MockTransport(upstream)))
    proxy.call("s-hostile", "browser_navigate", {"url": hostile})
    proxy.call("s-hostile", "browser_type", {"element": hostile, "ref": hostile, "text": hostile})

    assert spawned == [browser_tool.service_argv(45678, tmp_path / "browser-mcp" / "out")]
    assert not any(hostile in a for a in spawned[0])
    assert [p["arguments"] for p in seen][0] == {"url": hostile}  # the input went to the session, not the argv
