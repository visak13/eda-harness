"""S10 (s-b431082892): the updater's new seams, each with its collaborators faked: the uv receipt's extras, the
previous-MSI cache keyed on version and SHA256, the compat gate both paths share, the result files the tray reads,
and the runner's close/timeout/park/board-event steps. The real drill is v8/scripts/drill_update_in_place.ps1."""

from __future__ import annotations

import hashlib
import json
import os
import time
from pathlib import Path

import pytest

from edp8 import update_helper as uh
from edp8 import updater
from edp8.updater import UpdateError


@pytest.fixture
def home(monkeypatch, tmp_path):
    for k in ("EDP8_DATA", "EDP8_RUN_DIR", "EDP8_LOGS_DIR", "EDP_UPDATE_INSTALL_CMD"):
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setenv("EDP_HOME", str(tmp_path / "home"))
    return tmp_path / "home"


# ------------------------------------------------------------------------------------------ receipt extras

RECEIPT = """[tool]
requirements = [
    { name = "edp8", specifier = ">=0.9" },
    { name = "edp-contracts", path = "C:/w/edp_contracts-0.9.1-py3-none-any.whl" },
    { name = "proxy-tools", specifier = "==0.1.0" },
    { name = "extra-local", path = "C:/w/extra_local-1.0-py3-none-any.whl" },
    { name = "proxy_tools", specifier = "==0.1.0" },
]
"""


def test_receipt_extras_keep_what_is_not_the_releases_own(tmp_path):
    f = tmp_path / "uv-receipt.toml"
    f.write_text(RECEIPT, encoding="utf-8")
    assert updater.receipt_extras(f) == ["proxy-tools==0.1.0", "C:/w/extra_local-1.0-py3-none-any.whl"]
    assert updater.receipt_extras(tmp_path / "missing.toml") == []
    f.write_text("not [ toml", encoding="utf-8")
    assert updater.receipt_extras(f) == []


def test_install_argv_carries_the_extras_as_with(monkeypatch, home, tmp_path):
    monkeypatch.setattr(updater, "_uv", lambda: "uv")
    wheels = {w: tmp_path / f"{w}.whl" for w in updater.WHEELS}
    argv = updater.install_argv(wheels, extras=["proxy-tools==0.1.0"])
    assert argv[:4] == ["uv", "tool", "install", "--force"] and "tool upgrade" not in " ".join(argv)
    i = argv.index("proxy-tools==0.1.0")
    assert argv[i - 1] == "--with"


# ------------------------------------------------------------------------------------------ previous MSI cache

NAME = "Heronry Desktop-0.9.1.msi"


def _cache(home: Path, payload: bytes, listed: bytes | None = None) -> Path:
    d = home / "data" / "updates" / "0.9.1"
    d.mkdir(parents=True, exist_ok=True)
    (d / NAME).write_bytes(payload)
    (d / "SHA256SUMS").write_text(f"{hashlib.sha256(listed or payload).hexdigest()}  {NAME}\n", encoding="utf-8")
    return d / NAME


@pytest.fixture
def cache_root(monkeypatch, home):
    monkeypatch.setenv("EDP8_DATA", str(home / "data"))
    return home


def _release(payload: bytes) -> updater.Release:
    return updater.Release("0.9.1", {NAME: "ignored"}, {NAME: hashlib.sha256(payload).hexdigest()})


def test_a_cached_msi_is_used_only_while_it_matches_the_releases_sum(monkeypatch, cache_root):
    msi = _cache(cache_root, b"good")
    monkeypatch.setattr(updater, "fetch_msi_release", lambda url, tag=None: _release(b"good"))
    monkeypatch.setattr(updater, "download", lambda rel: pytest.fail("a matching cache must not download"))
    assert updater.secure_previous_msi("0.9.1") == msi


def test_a_stale_cached_msi_is_replaced_by_the_verified_release_copy(monkeypatch, cache_root):
    msi = _cache(cache_root, b"stale")  # same name, same version, different bytes than the release now lists
    monkeypatch.setattr(updater, "fetch_msi_release", lambda url, tag=None: _release(b"fresh"))
    got = []

    def download(rel):
        got.append(rel.version)
        msi.write_bytes(b"fresh")
        (msi.parent / "SHA256SUMS").write_text(f"{rel.sums[NAME]}  {NAME}\n", encoding="utf-8")
        return {"msi": msi}
    monkeypatch.setattr(updater, "download", download)
    assert updater.secure_previous_msi("0.9.1") == msi and got == ["0.9.1"]


def test_a_release_that_disowns_the_copy_gives_no_rollback(monkeypatch, cache_root):
    _cache(cache_root, b"stale")
    monkeypatch.setattr(updater, "fetch_msi_release", lambda url, tag=None: _release(b"fresh"))

    def download(rel):
        raise UpdateError("SHA256 mismatch")
    monkeypatch.setattr(updater, "download", download)
    assert updater.secure_previous_msi("0.9.1") is None


def test_offline_the_verified_cache_is_all_there_is(monkeypatch, cache_root):
    def offline(url, tag=None):
        raise OSError("no network")
    monkeypatch.setattr(updater, "fetch_msi_release", offline)
    assert updater.secure_previous_msi("0.9.1") is None
    msi = _cache(cache_root, b"good")
    assert updater.secure_previous_msi("0.9.1") == msi
    _cache(cache_root, b"tampered", listed=b"good")  # its own recorded sum no longer matches
    assert updater.secure_previous_msi("0.9.1") is None


# ------------------------------------------------------------------------------------------ compat gate

def _rows(*oks):
    return [{"workflow": f"w{i}", "version": 1, "ok": ok, "errors": [] if ok else ["bad"]} for i, ok in enumerate(oks)]


def test_compat_gate_outcomes(tmp_path, capsys):
    db = tmp_path / "board.db"
    db.write_bytes(b"x")
    boom = lambda: pytest.fail("not run")  # noqa: E731
    assert updater._compat_gate({"skip-compat": True}, db, boom, "2.0.0") is None
    assert updater._compat_gate({}, tmp_path / "none.db", boom, "2.0.0") is None  # no DB yet: nothing to check
    assert updater._compat_gate({}, db, lambda: (0, _rows(True), ""), "2.0.0") is None
    assert updater._compat_gate({}, db, lambda: (1, _rows(True, False), ""), "2.0.0") == 1
    assert "1 workflow(s) fail on 2.0.0" in capsys.readouterr().out
    with pytest.raises(UpdateError, match="could not run.*exit 2: usage"):
        updater._compat_gate({}, db, lambda: (2, [], "usage"), "2.0.0")


def test_msi_compat_check_hands_the_runner_the_extract_and_reads_its_answer(monkeypatch, home, tmp_path):
    import edp_contracts.proc as proc
    seen = {}

    def detach(argv, **kw):
        seen["argv"] = argv
        plan = json.loads(Path(argv[-1]).read_text(encoding="utf-8"))
        seen["plan"] = plan
        Path(plan["compat_out"]).write_text(json.dumps({"rc": 1, "stdout": json.dumps(_rows(False)), "stderr": "e"}),
                                            encoding="utf-8")
        return (type("P", (), {"pid": 1})(),)
    monkeypatch.setattr(proc, "detach", detach)
    stub = tmp_path / "rt" / "heronry.exe"
    rc, rows, err = updater.msi_compat_check(tmp_path / "new.msi", tmp_path / "board.db", stub)
    assert (rc, err) == (1, "e") and rows[0]["ok"] is False
    assert seen["argv"][0] == str(stub) and "--compat" in seen["argv"]
    assert seen["plan"]["extract"]["dir"].endswith("x")  # a short target: a deep one overflows MAX_PATH (1320)
    assert seen["plan"]["compat_args"][:3] == ["workflows", "check", "--db"]


# ------------------------------------------------------------------------------------------ result files

def test_the_newest_result_wins_and_reads_in_plain_words(monkeypatch, home):
    ud, run = updater.update_dir(), home / "run"
    monkeypatch.setenv("EDP8_RUN_DIR", str(run))
    ud.mkdir(parents=True)
    run.mkdir(parents=True)
    assert updater.last_result() is None
    old = ud / updater.RESULT_NAME
    old.write_text(json.dumps({"state": "ok", "to": "1.0", "finished_at": "t1", "resumed": ["a", "b"]}), encoding="utf-8")
    os.utime(old, (time.time() - 100, time.time() - 100))
    (run / updater.RESULT_NAME).write_text(json.dumps(
        {"state": "rolled_back", "from": "0.9", "reason": "health check failed", "finished_at": "t2"}), encoding="utf-8")
    res = updater.last_result()
    assert res["finished_at"] == "t2" and res["_seen"] is False
    assert updater.result_text(res) == "Rolled back to 0.9: health check failed"
    updater.mark_result_seen(res)
    assert updater.last_result()["_seen"] is True
    assert updater.result_text({"state": "ok", "to": "1.0", "resumed": ["a", "b"]})         == f"Updated to 1.0; 2 seat(s) resumed. {updater.MCP_RECONNECT_HINT}."  # RC2 item 6
    assert updater.result_text({"state": "failed", "reason": "boom", "recover_hint": "reinstall 0.9"}) \
        == "Failed: boom - reinstall 0.9"
    assert updater.result_text({"state": "failed", "reason": "boom; reinstall 0.9", "recover_hint": "reinstall 0.9"}) \
        == "Failed: boom; reinstall 0.9"


def test_a_plan_without_an_outcome_is_staged_until_it_goes_stale(home):
    ud = updater.update_dir()
    ud.mkdir(parents=True)
    assert updater.update_staged() is False
    plan = ud / "update-plan.json"
    plan.write_text("{}", encoding="utf-8")
    assert updater.update_staged() is True
    res = ud / updater.RESULT_NAME
    res.write_text("{}", encoding="utf-8")
    os.utime(res, (time.time() + 5, time.time() + 5))
    assert updater.update_staged() is False  # the runner wrote its outcome after the plan
    os.utime(res, (time.time() - 9999, time.time() - 9999))
    os.utime(plan, (time.time() - updater.STAGED_MAX_AGE_S - 60,) * 2)
    assert updater.update_staged() is False  # an abandoned plan never locks the update out


# ------------------------------------------------------------------------------------------ the runner

def _staged_msis(tmp_path) -> dict:
    """S13 F6: the helper installs only the bytes the updater verified, so a plan names real files and their sums."""
    import hashlib
    out = {}
    for key, name in (("msi", "new.msi"), ("previous_msi", "old.msi")):
        f = tmp_path / name
        f.write_bytes(f"synthetic {name}".encode())
        out[key], out[f"{key}_sha256"] = str(f), hashlib.sha256(f.read_bytes()).hexdigest()
    return out


@pytest.fixture
def rplan(tmp_path):
    return {"kind": "msi", "caller_pid": 0, "from_version": "0.9.1", "to_version": "0.9.2",
            **_staged_msis(tmp_path), "upgrade_code": "{UC}", "install_dir": str(tmp_path / "inst"),
            "pool_url": "http://127.0.0.1:1", "stop_argv": ["stop"], "start_argv": ["start"], "app_argv": None,
            "health_url": "http://x/v1/health", "db": "", "backup": "", "log": str(tmp_path / "update.log"),
            "result": str(tmp_path / "result.json"), "recover_hint": "reinstall", "holder_wait_s": 0}


def test_the_runner_closes_only_the_app_windows_it_was_told_about(monkeypatch, rplan):
    killed = []
    monkeypatch.setattr(uh, "_pid_alive", lambda pid: pid != 12)
    monkeypatch.setattr(uh.subprocess, "run", lambda argv, **kw: killed.append(argv[-1]))
    Path(rplan["log"]).touch()
    monkeypatch.setattr(uh, "_proc_identity", lambda pid: (100.0, "C:/i/App.exe"))
    seen = {"exe": "C:/i/App.exe", "created": 100.2}
    uh._close_app({**rplan, "app_pids": [11, 12, os.getpid()],
                   "app_procs": {"11": seen, "12": seen, str(os.getpid()): seen}})
    assert killed == ["11"]  # 12 is already gone, and the runner never closes itself
    killed.clear()
    uh._close_app(rplan)
    assert killed == []


def test_the_runner_does_not_close_a_pid_that_is_no_longer_the_app(monkeypatch, rplan):
    killed = []
    monkeypatch.setattr(uh, "_pid_alive", lambda pid: True)
    monkeypatch.setattr(uh.subprocess, "run", lambda argv, **kw: killed.append(argv[-1]))
    Path(rplan["log"]).touch()
    monkeypatch.setattr(uh, "_proc_identity", lambda pid: (500.0, "C:/i/App.exe"))  # a pid reused later
    plan = {**rplan, "app_pids": [21, 22, 23],
            "app_procs": {"21": {"exe": "C:/i/App.exe", "created": 100.0},   # same image, other start time
                          "22": {"exe": "C:/other/x.exe", "created": 500.0}}}  # same start, other image; 23 unknown
    uh._close_app(plan)
    assert killed == []
    assert "not closing pid 21" in Path(rplan["log"]).read_text(encoding="utf-8")


def _msi_run(monkeypatch, rplan, *, timeout_leaves_new: bool, health=None):
    state = {"version": "0.9.1", "calls": []}

    def msiexec(p, what, args, log_name):
        state["calls"].append(args[0])
        if args[0] == "/i" and args[1].endswith("new.msi"):
            if timeout_leaves_new:
                state["version"] = "0.9.2"
            return uh.MSI_TIMEOUT
        if args[0] == "/x":
            state["version"] = None
            return 0
        state["version"] = "0.9.1"
        return 0
    monkeypatch.setattr(uh, "related_products", lambda c: [{"code": "{N}", "version": state["version"]}])
    monkeypatch.setattr(uh, "_msiexec", msiexec)
    monkeypatch.setattr(uh, "_run", lambda *a, **k: True)
    monkeypatch.setattr(uh, "_health_version", lambda url, wait_s=0: health or state["version"])
    monkeypatch.setattr(uh, "holders", lambda d, images_only=False, **kw: [])
    monkeypatch.setattr(uh, "install_procs", lambda folder: [])
    monkeypatch.setattr(uh, "_park", lambda p: [])
    monkeypatch.setattr(uh, "_resume", lambda p, hs: [])
    monkeypatch.setattr(uh, "_pid_alive", lambda pid: False)
    monkeypatch.setattr(uh, "_msi_busy", lambda: False)
    Path(rplan["log"]).touch()
    path = Path(rplan["result"]).with_name("plan.json")
    path.write_text(json.dumps(rplan), encoding="utf-8")
    uh.main(str(path))
    return json.loads(Path(rplan["result"]).read_text(encoding="utf-8")), state["calls"]


def test_a_msiexec_that_outlives_its_timeout_with_nothing_changed_rolls_back_without_reinstalling(monkeypatch, rplan):
    res, calls = _msi_run(monkeypatch, rplan, timeout_leaves_new=False)
    assert res["state"] == "rolled_back" and "did not finish" in res["reason"]
    assert calls == ["/i"]


def test_a_rollback_is_only_rolled_back_when_the_board_reports_the_old_version(monkeypatch, rplan):
    # whatever answers the health URL (another home's board on the port) is not proof the old version is back
    res, _ = _msi_run(monkeypatch, rplan, timeout_leaves_new=False, health="9.9.9")
    assert res["state"] == "failed" and "did not come back" in res["reason"] and res["health_version"] == "9.9.9"


def test_a_msiexec_that_outlives_its_timeout_after_committing_is_removed_and_the_old_msi_reinstalled(monkeypatch, rplan):
    res, calls = _msi_run(monkeypatch, rplan, timeout_leaves_new=True)
    assert res["state"] == "rolled_back" and res["installed"] == "0.9.1"
    assert calls == ["/i", "/x", "/i"]


def test_the_outcome_is_posted_to_the_board_with_the_admin_token_and_failures_are_skipped(monkeypatch, tmp_path, rplan):
    tok = tmp_path / "admin.token"
    tok.write_text("s3cret\n", encoding="utf-8")
    Path(rplan["log"]).touch()
    plan = {**rplan, "board_url": "http://127.0.0.1:9", "admin_token_file": str(tok), "board_ours": True}
    sent = []
    monkeypatch.setattr(uh, "_http", lambda url, method="GET", timeout=0, body=None, token=None:
                        sent.append((url, method, token, body)))
    uh._post_event(plan, "rolled_back", "health check failed")
    (url, method, token, body), = sent
    assert (url, method, token) == ("http://127.0.0.1:9/v1/service_event", "POST", "s3cret")
    assert body["service"] == "app" and "0.9.1 -> 0.9.2: rolled_back: health check failed" in body["reason"]
    assert "s3cret" not in Path(rplan["log"]).read_text(encoding="utf-8")

    def down(*a, **k):
        raise OSError("board is stopped")
    monkeypatch.setattr(uh, "_http", down)
    uh._post_event(plan, "ok", "")  # best effort: no raise
    assert "board event not recorded" in Path(rplan["log"]).read_text(encoding="utf-8")
    sent.clear()
    monkeypatch.setattr(uh, "_http", lambda *a, **k: sent.append(1))
    uh._post_event({**plan, "board_url": None}, "ok", "")
    uh._post_event({**plan, "board_ours": False}, "ok", "")  # a board this home does not own never gets the token
    assert sent == []


class _FakeLauncher:
    def __init__(self, owners):
        self.owners = owners

    def owner(self, svc):
        return (self.owners[svc], {})

    def port(self, svc):
        return {"pool": 19300, "board": 19400}[svc]

    def url(self, svc):
        return f"http://127.0.0.1:{self.port(svc)}"


def test_plan_endpoints_are_present_only_for_services_this_home_owns(home):
    both = updater._owned_endpoints(_FakeLauncher({"pool": "ours", "board": "ours"}))
    assert both["pool_url"] == "http://127.0.0.1:19300" and both["board_url"] == "http://127.0.0.1:19400"
    assert both["pool_ours"] and both["board_ours"] and both["admin_token_file"]
    # a private install whose own services are down next to a running fleet: nothing may be parked or sent a token
    for state in ("free", "foreign"):
        got = updater._owned_endpoints(_FakeLauncher({"pool": state, "board": state}))
        assert got == {"pool_ours": False, "board_ours": False}


def test_the_uv_path_never_parks_a_pool_it_does_not_own(monkeypatch, home):
    calls = _uv_apply(monkeypatch, pool_owner="foreign")
    assert "park" not in calls and "stop" in calls


def test_the_uv_path_resumes_the_seats_it_parked_when_the_update_cannot_start(monkeypatch, home):
    calls = _uv_apply(monkeypatch, pool_owner="ours", live=["engineer.x"])
    assert calls == ["park", "stop", "resume:engineer.x"]


def _uv_apply(monkeypatch, *, pool_owner: str, live=()):
    from edp8 import launcher, update_helper
    monkeypatch.setenv("EDP_DEV", "0")
    monkeypatch.setattr(launcher, "bundled", lambda: False)
    monkeypatch.setattr(updater, "_uv_tool_env", lambda: True)
    monkeypatch.setattr(updater, "current_version", lambda: "1.0.0")
    monkeypatch.setattr(updater, "fetch_release", lambda url, tag=None: updater.Release("2.0.0", {}))
    monkeypatch.setattr(updater, "download", lambda rel: {})
    monkeypatch.setattr(updater, "secure_previous", lambda version, url=None: {"edp8": Path("prev.whl")})
    monkeypatch.setattr(updater, "backup_db", lambda db, v: Path("b.db"))
    monkeypatch.setattr(updater, "_compat_gate", lambda *a, **k: None)
    monkeypatch.setattr(launcher, "owner", lambda svc, **k: (pool_owner if svc == "pool" else "free", {}))
    monkeypatch.setattr(launcher, "live_seats", lambda: list(live))
    calls: list[str] = []
    monkeypatch.setattr(update_helper, "_park", lambda plan: calls.append("park") or list(live))
    monkeypatch.setattr(update_helper, "_resume_now",
                        lambda plan, hs: calls.append("resume:" + ",".join(hs)) or list(hs))

    def stop():
        calls.append("stop")
        raise RuntimeError("a service did not stop")
    monkeypatch.setattr(updater, "_stop_all", stop)
    with pytest.raises(RuntimeError):
        updater.apply({})
    return calls


def test_foreign_dirs_also_guards_an_install_with_no_edp_home(monkeypatch, tmp_path):
    from edp_contracts import settings
    for k in ("EDP_HOME", "EDP8_HOME", "EDP8_DATA", "EDP8_RUN_DIR"):
        monkeypatch.delenv(k, raising=False)
    assert settings.foreign_dirs() == []  # nothing inherited: the platform defaults
    fleet = tmp_path / "fleet" / "run"
    monkeypatch.setenv("EDP8_RUN_DIR", str(fleet))  # inherited from a shell that belongs to another home
    assert [d.split("=")[0] for d in settings.foreign_dirs()] == ["EDP8_RUN_DIR"]
    with pytest.raises(settings.ForeignHome):
        settings.home_guard()


def test_the_uv_path_resumes_the_seats_the_updater_parked(monkeypatch, rplan, tmp_path):
    plan = {k: v for k, v in rplan.items() if k not in ("kind", "msi", "previous_msi", "upgrade_code", "install_dir")}
    plan.update(install_argv=["install"], rollback_install_argv=["old"], parked=["engineer.a"])
    resumed = []
    monkeypatch.setattr(uh, "_run", lambda p, what, argv, timeout=0: True)
    monkeypatch.setattr(uh, "_healthy", lambda url, wait_s=0: True)
    monkeypatch.setattr(uh, "_resume", lambda p, hs: resumed.append(list(hs)) or list(hs))
    monkeypatch.setattr(uh, "_pid_alive", lambda pid: False)
    Path(plan["log"]).touch()
    path = tmp_path / "plan.json"
    path.write_text(json.dumps(plan), encoding="utf-8")
    assert uh.main(str(path)) == 0
    res = json.loads(Path(plan["result"]).read_text(encoding="utf-8"))
    assert res["state"] == "ok" and res["parked"] == res["resumed"] == ["engineer.a"] and resumed == [["engineer.a"]]
    # an install that fails is rolled back, the old version comes up, and the seats are resumed after that
    resumed.clear()
    calls = []
    monkeypatch.setattr(uh, "_run", lambda p, what, argv, timeout=0: calls.append(what) or what != "install")
    assert uh.main(str(path)) == 1
    res = json.loads(Path(plan["result"]).read_text(encoding="utf-8"))
    assert res["state"] == "rolled_back" and res["resumed"] == ["engineer.a"] and resumed == [["engineer.a"]]
    assert calls == ["install", "stop", "reinstall previous", "start previous"]


# ------------------------------------------------------------------------------------------ admin

def test_admin_refusal_no_longer_turns_back_a_bundle_or_live_seats(monkeypatch, home):
    from edp8 import launcher
    from edp8.admin import updates
    monkeypatch.setenv("EDP_DEV", "0")
    monkeypatch.setattr(launcher, "bundled", lambda: True)
    monkeypatch.setattr(updater, "update_staged", lambda: False)
    monkeypatch.setattr(updater, "install_scope_busy", lambda: False)
    monkeypatch.setattr(launcher, "live_seats", lambda: ["engineer.x (pid 7, active)"])
    assert updates.refusal(force=False) is None  # parked and resumed by the update, not refused
    monkeypatch.setattr(launcher, "live_seats", lambda: None)
    assert "couldn't confirm" in updates.refusal(force=False) and updates.refusal(force=True) is None
    monkeypatch.setattr(updater, "update_staged", lambda: True)
    assert "already running" in updates.refusal(force=True)
    monkeypatch.setattr(updater, "update_staged", lambda: False)
    monkeypatch.setattr(updater, "install_scope_busy", lambda: True)
    assert "Installer is busy" in updates.refusal(force=True)


# ------------------------------------------------------------------------------------------ release asset names

def test_github_dots_the_spaces_of_an_msi_name_and_the_sums_line_still_matches(monkeypatch):
    h = "b" * 64
    assets = [{"name": "Heronry.Desktop-1.0.0.msi", "browser_download_url": "https://x/Heronry.Desktop-1.0.0.msi"},
              {"name": "SHA256SUMS", "browser_download_url": "https://x/SHA256SUMS"},
              {"name": "install.ps1", "browser_download_url": "https://x/install.ps1"}]

    class R:
        def raise_for_status(self):
            pass

        def json(self):
            return {"assets": assets}
    monkeypatch.setattr(updater, "_get", lambda *a, **k: R())
    monkeypatch.setattr(updater, "_read", lambda src: f"{h}  Heronry Desktop-1.0.0.msi\n".encode())
    rel = updater.fetch_msi_release(None)
    assert rel.version == "1.0.0" and list(rel.files) == ["Heronry.Desktop-1.0.0.msi"]
    assert rel.sums["Heronry.Desktop-1.0.0.msi"] == h  # the sum is found under the asset's own name: download() verifies it


def test_the_gui_exe_is_named_after_the_product_not_only_the_brand(tmp_path):
    from edp8.brand import DESKTOP_APP_NAME
    (tmp_path / "heronry.exe").touch()
    assert updater.gui_exe_name(tmp_path) == f"{DESKTOP_APP_NAME}.exe"  # nothing there yet: the brand's name
    (tmp_path / "Side By Side.exe").touch()
    assert updater.gui_exe_name(tmp_path, "Side By Side") == "Side By Side.exe"  # a drill build with its own name
    (tmp_path / f"{DESKTOP_APP_NAME}.exe").touch()
    assert updater.gui_exe_name(tmp_path, "Missing") == f"{DESKTOP_APP_NAME}.exe"
    assert updater.gui_exe_name(tmp_path, None) == f"{DESKTOP_APP_NAME}.exe"
