"""S2 (s-3c8c2512d6): the `code` service — pinned code-server install, start/stop scripts, edp.ps1 wiring.

Static checks run everywhere on Windows. The install and live-instance tests use the pinned install
and download cache that `scripts/install-code-server.ps1` leaves under `v8/.tools/code-server/` and
skip when they are absent. A live instance here always runs on a SPARE port with its own data and run
dirs; the fleet's `code` service (:9410), board and other services are never touched.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import socket
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

import pytest

V8 = Path(__file__).resolve().parents[1]
ROOT = V8.parent
PS = shutil.which("powershell.exe") or shutil.which("powershell")
SCRIPTS = {n: V8 / "scripts" / n for n in ("install-code-server.ps1", "start-code.ps1", "stop-code.ps1")}
LOCK = json.loads((V8 / "vscode-ext" / "code-server.lock.json").read_text(encoding="utf-8"))
ARCHIVE = V8 / ".tools" / "code-server" / "_download" / LOCK["asset"]
INSTALLED = V8 / ".tools" / "code-server" / LOCK["version"] / ".verified"

pytestmark = pytest.mark.skipif(PS is None or sys.platform != "win32", reason="Windows PowerShell 5.1 only")


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _ps(script: Path, *args: str, env: dict[str, str] | None = None, timeout: int = 300):
    cmd = [PS, "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(script), *args]
    return subprocess.run(cmd, env=env, capture_output=True, text=True, timeout=timeout)


def _env(tmp_path: Path, port: int) -> dict[str, str]:
    env = {k: v for k, v in os.environ.items() if not re.match(r"EDP8?_", k)}
    env.update(EDP_CODE_PORT=str(port), EDP8_RUN_DIR=str(tmp_path / "run"), EDP_CODE_DATA=str(tmp_path / "data"))
    return env


def _listener(port: int) -> int | None:
    out = subprocess.run([PS, "-NoProfile", "-Command",
                          f"(Get-NetTCPConnection -LocalPort {port} -State Listen -ErrorAction SilentlyContinue | Select-Object -First 1).OwningProcess"],
                         capture_output=True, text=True, timeout=60).stdout.strip()
    return int(out) if out else None


# ── static ──────────────────────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("name", sorted(SCRIPTS))
def test_scripts_parse_under_windows_powershell_51(name):
    probe = (
        "$e=$null; [void][System.Management.Automation.Language.Parser]::ParseFile("
        f"'{SCRIPTS[name]}', [ref]$null, [ref]$e); \"$($PSVersionTable.PSVersion.Major).$($PSVersionTable.PSVersion.Minor) $($e.Count)\""
    )
    out = subprocess.run([PS, "-NoProfile", "-Command", probe], capture_output=True, text=True, timeout=60).stdout.split()
    assert out == ["5.1", "0"]
    assert SCRIPTS[name].read_bytes().isascii(), "ASCII keeps PS 5.1 from misreading a BOM-less file"


def test_scripts_never_kill_by_image_or_touch_global_state():
    for path in SCRIPTS.values():
        code = "\n".join(line.split("#", 1)[0] for line in path.read_text(encoding="utf-8").splitlines())
        assert not re.search(r"taskkill|Stop-Process\b[^\n]*-Name|Get-Process\s+-Name", code, re.I), path.name
        assert not re.search(r"SetEnvironmentVariable\([^)]*\"(User|Machine)\"|\$env:Path\s*=", code, re.I), path.name


def test_start_flags_bind_loopback_and_disable_update_telemetry_proxy():
    src = SCRIPTS["start-code.ps1"].read_text(encoding="utf-8")
    for flag in ("--disable-telemetry", "--disable-update-check", "--disable-proxy",
                 "--config", "--user-data-dir", "--extensions-dir"):
        assert flag in src, flag
    assert '$BINDHOST = "127.0.0.1"' in src
    # s-03c7e9168b: code-server binds a random inner loopback port with --auth password and a per-start
    # secret passed only by environment; the guard holds the service port
    assert '"--bind-addr", "${BINDHOST}:$INNER", "--auth", "password"' in src and '"--auth", "none"' not in src
    assert '"edp8.code_guard", "--port", "$PORT", "--upstream", "tcp:${BINDHOST}:$INNER"' in src
    assert "$env:HASHED_PASSWORD = $s" in src and "CODE_GUARD_SESSION" in src and "$SECRET" not in src.split("$flags = @(")[1].split(")")[0]
    # second opinion 20260925T174116Z-b3066925: trace logging would write the password out (--log info
    # outranks LOG_LEVEL) and an inherited cookie suffix would rename the cookie the guard injects
    assert '"--log", "info"' in src and '"LOG_LEVEL", "PASSWORD", "CODE_SERVER_COOKIE_SUFFIX", "VSCODE_OPTIONS"' in src
    assert "--verbose" not in src.split("$flags = @(")[1].split(")")[0]
    # the env strip is by prefix (dec-ea925a2d30), scoped to the launch and the CLI installs
    assert "'^EDP8?_'" in src and "WithoutFleetEnv {" in src
    # s-17c13096e5: the guard-session mint key reaches the guard only after code-server started (its
    # terminals never inherit it), never on a command line; the board reads it from code.json
    wrapper = src.split("$body = @(")[1].split("WriteUtf8 $wrap $body")[0]
    assert "Remove-Item Env:CODE_GUARD_MINT_HANDOFF" in wrapper.split("$p =Start-Process")[0]
    assert "$env:CODE_GUARD_MINT_KEY = $mk" in wrapper.split("$p =Start-Process")[1]
    assert "$MINTKEY" not in src.split("$flags = @(")[1].split(")")[0] and "$MINTKEY" not in src.split("$guardFlags = @(")[1].split(")")[0]
    assert "mint_key = $MINTKEY" in src


def test_extension_pins_are_exact_and_locked():
    pins = [l.strip() for l in (V8 / "vscode-ext" / "extensions.txt").read_text(encoding="utf-8").splitlines()
            if l.strip() and not l.startswith("#")]
    lock = json.loads((V8 / "vscode-ext" / "extensions.lock.json").read_text(encoding="utf-8"))["extensions"]
    ids = [p.split("@")[0] for p in pins]
    for p in pins:
        assert re.fullmatch(r"[\w-]+\.[\w-]+@\d+\.\d+\.\d+", p), p
        i, v = p.split("@")
        assert lock[i]["version"] == v and re.fullmatch(r"[0-9a-f]{64}", lock[i]["sha256"]), p
        assert lock[i]["url"].startswith("https://open-vsx.org/"), "Open VSX only"
    assert sorted(ids) == sorted(lock)
    required = {"ms-python.python", "detachhead.basedpyright", "dbaeumer.vscode-eslint", "eamodio.gitlens",
                "ms-playwright.playwright", "ms-vscode.powershell", "llvm-vs-code-extensions.vscode-clangd",
                "ms-python.vscode-python-envs", "ms-python.debugpy"}  # the last two: python's transitive pack
    assert required <= set(ids)
    assert ids.index("ms-python.vscode-python-envs") < ids.index("ms-python.python")


# ── install ─────────────────────────────────────────────────────────────────────────────────────

@pytest.mark.skipif(not ARCHIVE.exists(), reason="release tarball not in the download cache")
def test_install_rejects_a_tampered_checksum_and_leaves_nothing(tmp_path):
    lock = dict(LOCK, sha256="0" * 64)
    (tmp_path / "lock.json").write_text(json.dumps(lock), encoding="ascii")
    r = _ps(SCRIPTS["install-code-server.ps1"], "-Lock", str(tmp_path / "lock.json"),
            "-ToolsDir", str(tmp_path / "tools"), "-Archive", str(ARCHIVE))
    assert r.returncode == 2 and "sha256 mismatch" in r.stderr, r.stdout + r.stderr
    assert not (tmp_path / "tools" / LOCK["version"]).exists()
    assert not (tmp_path / "tools" / (LOCK["version"] + ".tmp")).exists()


@pytest.mark.skipif(not ARCHIVE.exists(), reason="release tarball not in the download cache")
def test_install_is_idempotent(tmp_path):
    args = ("-ToolsDir", str(tmp_path / "tools"), "-Archive", str(ARCHIVE))
    first = _ps(SCRIPTS["install-code-server.ps1"], *args)
    assert first.returncode == 0 and "installed at" in first.stdout, first.stdout + first.stderr
    marker = tmp_path / "tools" / LOCK["version"] / ".verified"
    assert marker.read_text().strip() == LOCK["sha256"]
    stamp = marker.stat().st_mtime_ns
    second = _ps(SCRIPTS["install-code-server.ps1"], *args)
    assert second.returncode == 0 and "(no-op)" in second.stdout, second.stdout + second.stderr
    assert marker.stat().st_mtime_ns == stamp


# ── start / stop ────────────────────────────────────────────────────────────────────────────────

def test_start_refuses_a_non_loopback_bind(tmp_path):
    env = _env(tmp_path, _free_port()) | {"EDP_CODE_HOST": "0.0.0.0"}
    r = _ps(SCRIPTS["start-code.ps1"], env=env)
    assert r.returncode == 2 and "binds 127.0.0.1 only" in r.stderr, r.stdout + r.stderr


def test_start_fails_loudly_on_a_foreign_listener_and_leaves_it(tmp_path):
    port = _free_port()
    fake = subprocess.Popen([sys.executable, "-m", "http.server", str(port), "--bind", "127.0.0.1"],
                            cwd=tmp_path, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        for _ in range(100):
            if _listener(port):
                break
            time.sleep(0.1)
        r = _ps(SCRIPTS["start-code.ps1"], env=_env(tmp_path, port))
        assert r.returncode == 3 and "leaving it alone" in r.stderr, r.stdout + r.stderr
        assert fake.poll() is None
    finally:
        subprocess.run(["taskkill", "/PID", str(fake.pid), "/T", "/F"], capture_output=True)


@pytest.mark.skipif(not INSTALLED.exists(), reason="pinned code-server not installed")
def test_a_spare_port_instance_starts_healthy_and_stops_only_itself(tmp_path):
    port = _free_port()
    env = _env(tmp_path, port)
    fleet_code = _listener(int(os.environ.get("EDP_CODE_PORT_FLEET", "9410")))
    r = _ps(SCRIPTS["start-code.ps1"], "-SkipExtensions", env=env)
    try:
        assert r.returncode == 0, r.stdout + r.stderr
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/healthz", timeout=5) as h:
            assert h.status == 200
        state = json.loads((tmp_path / "run" / "code.json").read_text(encoding="utf-8"))
        assert state["service"] == "code" and state["port"] == port and state["version"] == LOCK["version"]
        assert state["sha256"] == LOCK["sha256"] and state["pid"] and state["started_at"]
        # s-03c7e9168b: the guard holds the port and refuses a rebinding Host; code-server's own inner
        # port answers a cookie-less hit with its login.
        # s-17c13096e5: without the guard cookie the loopback Host gets 401 too; a one-time token minted
        # with the recorded mint key signs in once (302 + the cookie), and with the cookie the workbench
        # answers with no code-server login; the same token again is refused
        inner = state["inner_port"]
        assert state["guard_pid"] and inner and inner != port and len(state["mint_key"]) == 64
        req = urllib.request.Request(f"http://127.0.0.1:{port}/", headers={"Host": f"evil.invalid:{port}"})
        with pytest.raises(urllib.error.HTTPError) as refused:
            urllib.request.urlopen(req, timeout=5)
        assert refused.value.code == 421
        with pytest.raises(urllib.error.HTTPError) as refused:
            urllib.request.urlopen(f"http://127.0.0.1:{port}/", timeout=10)
        assert refused.value.code == 401
        from edp8.code_guard import mint_token
        token, _ = mint_token(state["mint_key"])
        no_redirect = urllib.request.build_opener(type("NoRedirect", (urllib.request.HTTPRedirectHandler,), {"redirect_request": lambda *a, **k: None}))
        with pytest.raises(urllib.error.HTTPError) as login:
            no_redirect.open(f"http://127.0.0.1:{port}/__edp/login?t={token}&next=%2F", timeout=10)
        assert login.value.code == 302 and login.value.headers["Location"] == "/"
        cookie = login.value.headers["Set-Cookie"].split(";")[0]
        assert cookie.startswith("edp-code-guard=") and "HttpOnly" in login.value.headers["Set-Cookie"]
        with urllib.request.urlopen(urllib.request.Request(f"http://127.0.0.1:{port}/", headers={"Cookie": cookie}), timeout=10) as r:
            assert r.status == 200 and "/login" not in r.url and b"workbench.js" in r.read()
        with pytest.raises(urllib.error.HTTPError) as replay:
            no_redirect.open(f"http://127.0.0.1:{port}/__edp/login?t={token}&next=%2F", timeout=10)
        assert replay.value.code == 401
        with urllib.request.urlopen(f"http://127.0.0.1:{inner}/", timeout=10) as r:
            assert r.url.split("?")[0].endswith("/login") and b'type="password"' in r.read()
        owner = subprocess.run([PS, "-NoProfile", "-Command", f"(Get-CimInstance Win32_Process -Filter 'ProcessId={_listener(port)}').CommandLine"],
                               capture_output=True, text=True, timeout=60).stdout
        assert "edp8.code_guard" in owner and f"--port {port}" in owner, owner
        cfg = (tmp_path / "data" / "config.yaml").read_text(encoding="utf-8")
        assert f"bind-addr: 127.0.0.1:{inner}" in cfg and "auth: password" in cfg and "hashed-password" not in cfg
        settings = json.loads((tmp_path / "data" / "user" / "User" / "settings.json").read_text(encoding="utf-8"))
        assert settings["extensions.autoUpdate"] is False
        assert settings["files.refactoring.autoSave"] is False  # qa m-7beeffa077: a rename never saves on its own
        assert {a["prefix"] for a in settings["gitlens.autolinks"]} == {"t-", "s-", "epic-", "m-"}
        assert all(a["url"].endswith(f"/ui/ticket/{a['prefix']}<num>") for a in settings["gitlens.autolinks"])
        for glob in ("**/.venv/**", "**/node_modules/**", "**/.data/**", "**/.run/**", "**/.tools/**", "**/web/dist/**"):
            assert settings["files.watcherExclude"][glob] is True
    finally:
        s = _ps(SCRIPTS["stop-code.ps1"], env=env)
    assert s.returncode == 0, s.stdout + s.stderr
    assert _listener(port) is None and not (tmp_path / "run" / "code.json").exists()
    if fleet_code:  # the fleet's code service on :9410 kept running, same pid
        assert _listener(int(os.environ.get("EDP_CODE_PORT_FLEET", "9410"))) == fleet_code
        assert "sweep skipped" in s.stdout


# ── edp.ps1 wiring ──────────────────────────────────────────────────────────────────────────────

def _edp(args: list[str], env: dict[str, str]):
    return subprocess.run([PS, "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(ROOT / "edp.ps1"), *args],
                          env=env, capture_output=True, text=True, timeout=120)


def _edp_env(tmp_path: Path) -> dict[str, str]:
    env = dict(os.environ)
    env["EDP8_RUN_DIR"] = str(tmp_path / "run")
    for var in ("EDP8_PORT", "EDP_BROKER_PORT", "EDP_POOL_PORT", "EDP8_MCP_PORT", "EDP_CODE_PORT"):
        env[var] = str(_free_port())
    return env


def test_edp_status_lists_code_and_all_never_includes_it(tmp_path):
    env = _edp_env(tmp_path)
    st = _edp(["status"], env)
    assert st.returncode == 0 and re.search(r"^code\s+down\b", st.stdout, re.M), st.stdout + st.stderr
    for verb in ("stop", "start", "restart"):
        r = _edp([verb, "all", "-WhatIf"], env)
        assert "code" not in re.sub(r"(?i)unicode|codex", "", r.stdout), (verb, r.stdout)


def test_edp_restart_code_runs_its_scripts_and_touches_nothing_else(tmp_path):
    r = _edp(["restart", "code", "-WhatIf"], _edp_env(tmp_path))
    assert r.returncode == 0, r.stdout + r.stderr
    assert r"WHATIF: stop code (pid none listening): powershell -File v8\scripts\stop-code.ps1" in r.stdout
    assert "WHATIF: start code on :" in r.stdout and "scripts\\start-code.ps1" in r.stdout
    for other in ("board", "broker", "pool", "mcp", "bridge", "supervisor"):
        assert other not in r.stdout, (other, r.stdout)
