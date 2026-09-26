"""MCP containment for a codex seat: discover-and-disable every server codex would load, fail-closed.

Moved out of the retired consult bridge (S4 s-733de6e29f, design-e963c656f5 §4.6); the codex seat is now
its only user. Containment is DISCOVER-AND-DISABLE, never a static denylist (a plugin can inject a server
a fixed list misses, e.g. `cua_repl`): every server `codex mcp list --json` reports at launch is disabled,
plus the features that load a server the list never reports (HIDDEN_SERVER_FEATURES). Discovery failure is
an error the caller must not launch through.
"""

from __future__ import annotations

import json
import subprocess

#: unreal-mcp stays a hard floor even if discovery returns nothing.
_MCP_FLOOR: tuple[str, ...] = ("unreal-mcp",)

#: A stdio server that has no `mcp_servers.<name>` table in config.toml (plugin-injected, e.g. cua_repl)
#: rejects a bare `-c mcp_servers.<name>.enabled=false` with "invalid transport"; this harmless stub
#: `command` makes the merge a valid (disabled) table, never launched. A url/http server instead takes a
#: bare `.enabled=false` (a command there is rejected as "url is not supported for stdio"; codex 0.153.4).
_MCP_STUB_COMMAND = "edp8-disabled"

#: Features that load an MCP server `codex mcp list` never reports (p-8b8c035f, codex 0.156.0: `apps`
#: carries the 73-tool `codex_apps` plugin-runtime server, live in every thread). Forced off in every seat.
HIDDEN_SERVER_FEATURES: tuple[str, ...] = ("apps",)


def _last_nonempty_line(text: str) -> str:
    for line in reversed(text.splitlines()):
        line = line.strip()
        if line:
            return line
    return "codex produced no output"


def discover_mcp_servers(codex: str, timeout_s: int = 30, *, env: dict[str, str] | None = None,
                         cwd: str | None = None) -> tuple[list[dict[str, str]], str | None]:
    """Enumerate every MCP server codex would load, via `codex mcp list --json`.
    Returns ([{name, transport}], None) or ([], error). FAIL-CLOSED: a non-zero exit or unparseable
    output is an error. A valid empty array is not an error (the unreal-mcp floor still applies).
    `env`/`cwd` = the LAUNCH context (CODEX_HOME, project config): discovery must see the same
    configuration the launched codex will load; default = this process's."""
    try:
        proc = subprocess.run(
            [codex, "mcp", "list", "--json"], env=env, cwd=cwd,
            stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            text=True, encoding="utf-8", errors="replace", timeout=timeout_s, check=False)
    except (OSError, subprocess.SubprocessError) as e:
        return [], f"`codex mcp list --json` could not run: {e}"
    if proc.returncode != 0:
        tail = _last_nonempty_line((proc.stdout or "") + "\n" + (proc.stderr or ""))
        return [], f"`codex mcp list --json` exited {proc.returncode}: {tail}"
    try:
        data = json.loads(proc.stdout or "")
    except ValueError as e:
        return [], f"`codex mcp list --json` output was not JSON: {e}"
    if not isinstance(data, list):
        return [], "`codex mcp list --json` did not return a JSON array"
    servers: list[dict[str, str]] = []
    for item in data:
        if not isinstance(item, dict):
            return [], "`codex mcp list --json` array held a non-object entry"
        name = item.get("name")
        if not isinstance(name, str) or not name:
            return [], "`codex mcp list --json` entry has no name"
        t = item.get("transport")
        transport = str(t.get("type") or "") if isinstance(t, dict) else ""
        servers.append({"name": name, "transport": transport})
    return servers, None


def mcp_disable_args(servers: list[dict[str, str]]) -> list[str]:
    """`-c` overrides that disable EVERY discovered server, plus the unreal-mcp floor if discovery missed
    it: a stdio server takes a stub `command` + `.enabled=false`, a url/http server a bare
    `.enabled=false`. Order-stable per input. PURE."""
    args: list[str] = []
    seen: set[str] = set()
    for s in servers:
        name = s["name"]
        seen.add(name)
        if s.get("transport") == "stdio":
            args += ["-c", f'mcp_servers.{name}.command="{_MCP_STUB_COMMAND}"',
                     "-c", f"mcp_servers.{name}.enabled=false"]
        else:
            args += ["-c", f"mcp_servers.{name}.enabled=false"]
    for floor in _MCP_FLOOR:
        if floor not in seen:
            args += ["-c", f"mcp_servers.{floor}.enabled=false"]
    return args


def mcp_containment_args(servers: list[dict[str, str]]) -> list[str]:
    """The whole MCP containment: every discovered server disabled (mcp_disable_args) plus every
    HIDDEN_SERVER_FEATURES feature off, so a server outside `codex mcp list` is gone too. PURE."""
    args = mcp_disable_args(servers)
    for feat in HIDDEN_SERVER_FEATURES:
        args += ["-c", f"features.{feat}=false"]
    return args


def mcp_disabled_names(servers: list[dict[str, str]]) -> list[str]:
    """Every discovered server name plus the floor."""
    return sorted({s["name"] for s in servers} | set(_MCP_FLOOR))
