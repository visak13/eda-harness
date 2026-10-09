"""t-732cf1dd92: the fleet's browser tool: installed once at the pinned version under <data>/tools/browser-mcp, under a
lock; system Chrome or a one-time chromium; every failure names its step; the ONE shared service runs HTTP on
loopback, headless and isolated (m-bb6902256d)."""
from __future__ import annotations

import json
import threading
from pathlib import Path

import pytest

from edp_contracts import browser_tool as bt


@pytest.fixture
def home(tmp_path, monkeypatch):
    monkeypatch.setenv("EDP8_DATA", str(tmp_path / "data"))
    monkeypatch.setenv("EDP_BROWSER_MCP", "1")
    monkeypatch.setenv("EDP_NODE_BIN", str(tmp_path / "node.exe"))
    calls: list[str] = []

    def fake_run(step, argv, cwd, timeout):
        calls.append(step)
        if step.startswith("npm install"):
            cli = bt._cli(Path(cwd))
            cli.parent.mkdir(parents=True, exist_ok=True)
            cli.write_text("// cli", encoding="utf-8")
    monkeypatch.setattr(bt, "_run", fake_run)
    monkeypatch.setattr(bt, "_npm", lambda node: ["npm"])
    return tmp_path, calls


def test_the_pinned_version_installs_once_under_the_data_dir(home, monkeypatch):
    tmp, calls = home
    monkeypatch.setattr(bt, "system_chrome", lambda: "C:/chrome.exe")
    assert bt.version() == "0.0.83"
    assert not bt.status()["ready"]
    assert bt.ensure_installed() == {"version": "0.0.83", "browser": "chrome"}
    assert bt.install_dir() == tmp / "data" / "tools" / "browser-mcp"
    assert calls == ["npm install @playwright/mcp@0.0.83"]
    bt.ensure_installed()
    assert calls == ["npm install @playwright/mcp@0.0.83"]  # ready: no second install
    assert bt.status()["ready"] and bt.status()["browser"] == "chrome"


def test_without_system_chrome_it_downloads_chromium_once_and_runs_it(home, monkeypatch):
    tmp, calls = home
    monkeypatch.setattr(bt, "system_chrome", lambda: None)
    argv = bt.service_argv(9555, tmp / "out")
    assert calls == ["npm install @playwright/mcp@0.0.83", "downloading chromium (no system Chrome)"]
    assert argv[argv.index("--browser") + 1] == "chromium"


def test_a_new_pinned_version_reinstalls(home, monkeypatch):
    tmp, calls = home
    monkeypatch.setattr(bt, "system_chrome", lambda: "C:/chrome.exe")
    bt.ensure_installed()
    monkeypatch.setenv("EDP_BROWSER_MCP_VERSION", "0.0.84")
    bt.ensure_installed()
    assert calls == ["npm install @playwright/mcp@0.0.83", "npm install @playwright/mcp@0.0.84"]


def test_two_spawns_at_once_install_once(home, monkeypatch):
    tmp, calls = home
    monkeypatch.setattr(bt, "system_chrome", lambda: "C:/chrome.exe")
    gate = threading.Event()
    real = bt._run

    def slow(step, argv, cwd, timeout):
        gate.wait(2)
        real(step, argv, cwd, timeout)
    monkeypatch.setattr(bt, "_run", slow)
    out: list = []
    ts = [threading.Thread(target=lambda: out.append(bt.ensure_installed())) for _ in range(2)]
    for t in ts:
        t.start()
    gate.set()
    for t in ts:
        t.join(10)
    assert len(out) == 2 and calls == ["npm install @playwright/mcp@0.0.83"]
    assert not (bt.install_dir() / "install.lock").exists()


def test_a_failed_step_raises_naming_it_and_leaves_no_ready_stamp(home, monkeypatch):
    tmp, _calls = home
    monkeypatch.setattr(bt, "system_chrome", lambda: None)

    def boom(step, argv, cwd, timeout):
        if step.startswith("npm install"):
            cli = bt._cli(Path(cwd)); cli.parent.mkdir(parents=True, exist_ok=True); cli.write_text("x")
            return
        raise bt.BrowserToolError(step, "exit 1: network down")
    monkeypatch.setattr(bt, "_run", boom)
    with pytest.raises(bt.BrowserToolError) as e:
        bt.ensure_installed()
    assert e.value.step == "downloading chromium (no system Chrome)" and "network down" in str(e.value)
    assert not bt.status()["ready"]


def test_node_missing_is_a_named_step(home, monkeypatch):
    monkeypatch.delenv("EDP_NODE_BIN")
    monkeypatch.setattr("shutil.which", lambda *_a, **_k: None)
    with pytest.raises(bt.BrowserToolError, match="finding node"):
        bt.ensure_installed()


def test_run_reports_a_failing_command_with_its_step(tmp_path):
    import sys
    with pytest.raises(bt.BrowserToolError, match="npm install x failed: exit 3"):
        bt._run("npm install x", [sys.executable, "-c", "import sys; print('E404'); sys.exit(3)"], tmp_path, 60)


def test_the_shared_service_is_loopback_http_headless_isolated_with_no_init_script(home, monkeypatch):
    tmp, _ = home
    monkeypatch.setattr(bt, "system_chrome", lambda: "C:/chrome.exe")
    a = bt.service_argv(9555, tmp / "out")
    assert a[0] == str(tmp / "node.exe") and a[1] == str(bt._cli(bt.install_dir()))
    assert a[a.index("--port") + 1] == "9555" and a[a.index("--host") + 1] == "127.0.0.1"
    # the host check is the whole Host header; its default `localhost:<port>` refused 127.0.0.1 (measured)
    assert a[a.index("--allowed-hosts") + 1] == "127.0.0.1:9555,localhost:9555"
    assert "--headless" in a and "--isolated" in a and "--shared-browser-context" not in a
    assert a[a.index("--browser") + 1] == "chrome"
    assert "--init-script" not in a  # one global script cannot sign in many seats: the proxy does (ruling 2a)
    assert int(a[a.index("--idle-timeout") + 1]) == bt.IDLE_TIMEOUT_MS


def test_the_host_acting_tools_are_dropped():
    assert bt.DROPPED == {"browser_run_code_unsafe", "browser_file_upload"}


def test_off_by_setting(monkeypatch):
    monkeypatch.setenv("EDP_BROWSER_MCP", "0")
    assert bt.enabled() is False
    monkeypatch.setenv("EDP_BROWSER_MCP", "1")
    assert bt.enabled() is True


def test_status_is_side_effect_free(home):
    st = bt.status()
    assert st["ready"] is False and not bt.install_dir().exists()
    assert json.dumps(st)


def test_system_chrome_reads_only_declared_os_settings(tmp_path, monkeypatch):
    """The real lookup, unpatched: 4cfd8020 asked for undeclared names and raised SettingsError at the first call."""
    import sys
    if sys.platform != "win32":
        pytest.skip("the Windows install roots")
    exe = tmp_path / "Google" / "Chrome" / "Application" / "chrome.exe"
    exe.parent.mkdir(parents=True)
    exe.write_text("", encoding="utf-8")
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    monkeypatch.setenv("ProgramFiles", str(tmp_path / "none"))
    monkeypatch.setenv("ProgramFiles(x86)", str(tmp_path / "none"))
    assert bt.system_chrome() == str(exe)
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "none"))
    assert bt.system_chrome() is None
