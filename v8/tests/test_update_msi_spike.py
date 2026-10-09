"""S2 spike (s-725ef36c03): the MSI runner's decisions, with msiexec, the pool and the board faked.

The real thing ran on a private install (v8/scripts/drill_update_in_place.ps1, evidence docs/evidence/e0cec-s2/);
this pins the branch logic: what is rolled back how, and what the result says."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from edp8 import update_helper as uh
from edp8.updater import _msi_version, parse_sums


def test_sha256sums_keeps_a_file_name_with_spaces():
    h = "a" * 64
    assert parse_sums(f"{h}  Heronry Desktop-0.9.1.msi\n{h} *edp8-0.9.1-py3-none-any.whl\n") == {
        "Heronry Desktop-0.9.1.msi": h, "edp8-0.9.1-py3-none-any.whl": h}


def test_versions_compare_on_the_numeric_release_segment():
    assert uh._same("0.9.2.dev0", "0.9.2")
    assert uh._same("0.9.2", "0.9.2.0")
    assert not uh._same("0.9.1", "0.9.2")
    assert not uh._same(None, "0.9.1")
    assert _msi_version("Heronry S2 Spike-0.9.2.dev0.msi") == "0.9.2.dev0"
    assert _msi_version("Heronry Desktop-0.9.1.msi") == "0.9.1"
    assert _msi_version("SHA256SUMS") is None


def test_a_run_dir_outside_the_home_is_foreign(monkeypatch, tmp_path):
    from edp8.updater import foreign_dirs
    monkeypatch.setenv("EDP_HOME", str(tmp_path / "home"))
    monkeypatch.delenv("EDP8_DATA", raising=False)
    monkeypatch.delenv("EDP8_RUN_DIR", raising=False)
    assert foreign_dirs() == []
    monkeypatch.setenv("EDP8_RUN_DIR", str(tmp_path / "fleet" / "run"))  # the S2 incident's inherited variable
    assert [d.split("=")[0] for d in foreign_dirs()] == ["EDP8_RUN_DIR"]


class Fake:
    """The installed product, msiexec and the board, as one small state machine."""

    def __init__(self, tmp: Path, *, msi_rc: int = 0, held: list[str] | None = None, healthy_new: bool = True):
        self.version, self.msi_rc, self.held, self.healthy_new = "0.9.1", msi_rc, held or [], healthy_new
        self.calls: list[str] = []
        self.up = True

    def related(self, _code):
        return [{"code": "{OLD}" if self.version == "0.9.1" else "{NEW}", "version": self.version}]

    def msiexec(self, plan, what, args, log_name):
        self.calls.append(f"{args[0]} {args[1]}")
        if args[0] == "/x":
            self.version = None
            return 0
        if args[1].endswith("new.msi"):
            if self.msi_rc == 0:
                self.version = "0.9.2"
            return self.msi_rc
        self.version = "0.9.1"
        return 0

    def run(self, plan, what, argv, timeout=0):
        self.calls.append(what)
        self.up = what == "start"
        return True

    def health(self, url, wait_s=0):
        if not self.up or (self.version == "0.9.2" and not self.healthy_new):
            return None
        return "0.9.2.dev0" if self.version == "0.9.2" else "0.9.1"


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
def plan(tmp_path):
    return {"kind": "msi", "caller_pid": 0, "from_version": "0.9.1", "to_version": "0.9.2.dev0",
            **_staged_msis(tmp_path), "upgrade_code": "{UC}",
            "install_dir": str(tmp_path / "inst"), "pool_url": "http://127.0.0.1:1", "stop_argv": ["stop"],
            "start_argv": ["start"], "app_argv": None, "health_url": "http://x/v1/health", "db": "", "backup": "",
            "log": str(tmp_path / "update.log"), "result": str(tmp_path / "result.json"), "recover_hint": "reinstall",
            "holder_wait_s": 0}


def _go(monkeypatch, plan, fake, parked=("engineer.a",), procs=(), park=None, seats=None):
    monkeypatch.setattr(uh, "related_products", fake.related)
    monkeypatch.setattr(uh, "_msiexec", fake.msiexec)
    monkeypatch.setattr(uh, "_run", fake.run)
    monkeypatch.setattr(uh, "_health_version", fake.health)
    monkeypatch.setattr(uh, "holders", lambda d, images_only=False, **kw: list(fake.held))
    monkeypatch.setattr(uh, "install_procs", lambda folder: list(procs))  # what else runs from the install folder
    monkeypatch.setattr(uh, "seat_feeds", lambda folder, ps=None: [  # the live seat above each feed: none by default
        {"feed": f, "seat": (seats or {}).get(f["pid"])} for f in (ps if ps is not None else procs)
        if "edp8.feed_driver" in f["cmdline"]], raising=False)
    monkeypatch.setattr(uh, "_park", park or (lambda p: list(parked)))
    monkeypatch.setattr(uh, "_resume", lambda p, hs: list(hs))
    monkeypatch.setattr(uh, "_pid_alive", lambda pid: False)
    monkeypatch.setattr(uh, "_msi_busy", lambda: False)
    Path(plan["log"]).touch()
    path = Path(plan["result"]).with_name("plan.json")
    path.write_text(json.dumps(plan), encoding="utf-8")
    rc = uh.main(str(path))
    return rc, json.loads(Path(plan["result"]).read_text(encoding="utf-8"))


def test_upgrade_installs_without_uninstall_and_resumes(monkeypatch, plan, tmp_path):
    fake = Fake(tmp_path)
    rc, res = _go(monkeypatch, plan, fake)
    assert (rc, res["state"], res["reason"]) == (0, "ok", "")
    assert [c for c in fake.calls if c.startswith("/")] == [f"/i {plan['msi']}"]
    assert res["parked"] == res["resumed"] == ["engineer.a"] and res["installed"] == "0.9.2"
    assert set(res["timings"]) >= {"parked", "stopped", "holders_checked", "installed", "relaunched", "resumed"}


def test_failed_msiexec_relaunches_the_old_version_without_reinstalling(monkeypatch, plan, tmp_path):
    fake = Fake(tmp_path, msi_rc=1603)
    rc, res = _go(monkeypatch, plan, fake)
    assert res["state"] == "rolled_back" and "msiexec exit 1603" in res["reason"]
    assert "rolled its changes back" in res["reason"]
    assert [c for c in fake.calls if c.startswith("/")] == [f"/i {plan['msi']}"]  # no /x, no second /i
    assert res["installed"] == "0.9.1" and res["health_version"] == "0.9.1"


def test_a_held_file_installs_nothing(monkeypatch, plan, tmp_path):
    fake = Fake(tmp_path, held=["powershell (pid 42)"])
    rc, res = _go(monkeypatch, plan, fake)
    assert res["state"] == "rolled_back" and "held by powershell (pid 42)" in res["reason"]
    assert not [c for c in fake.calls if c.startswith("/")]


def test_an_unhealthy_new_version_is_removed_and_the_cached_msi_reinstalled(monkeypatch, plan, tmp_path):
    fake = Fake(tmp_path, healthy_new=False)
    rc, res = _go(monkeypatch, plan, fake)
    assert res["state"] == "rolled_back" and "health check" in res["reason"]
    assert [c for c in fake.calls if c.startswith("/")] == [f"/i {plan['msi']}", "/x {NEW}", f"/i {plan['previous_msi']}"]
    assert res["installed"] == "0.9.1"


def test_reboot_pending_counts_as_a_change_and_is_rolled_back(monkeypatch, plan, tmp_path):
    fake = Fake(tmp_path, msi_rc=3010)
    fake_msiexec = fake.msiexec

    def msiexec(p, what, args, log_name):  # 3010: the new version is registered, files wait for a reboot
        rc = fake_msiexec(p, what, args, log_name)
        if args[1].endswith("new.msi"):
            fake.version = "0.9.2"
        return rc
    monkeypatch.setattr(fake, "msiexec", msiexec)
    rc, res = _go(monkeypatch, plan, fake)
    assert res["state"] == "rolled_back" and "3010" in res["reason"]
    assert "/x {NEW}" in fake.calls


def test_the_drill_fault_switch_is_a_declared_setting(monkeypatch):
    # the first rebuilt drill died here: env_raw() refuses an undeclared name, before anything changed
    from edp8 import settings
    monkeypatch.setenv("HERONRY_UPDATE_FAULT", "unhealthy")
    assert settings.env_raw("HERONRY_UPDATE_FAULT") == "unhealthy"


def test_an_old_version_left_broken_by_a_killed_install_is_repaired_from_the_cached_msi(monkeypatch, plan, tmp_path):
    # S2 drill: the msiexec client was killed on a modal 1335 box; the service's own rollback was still running,
    # so the first relaunch found a half-restored folder. The runner repairs from the cached MSI (/fa).
    fake = Fake(tmp_path, msi_rc=-1)
    broken = {"on": True}
    health, msiexec = fake.health, fake.msiexec

    def health_(url, wait_s=0):
        return None if broken["on"] else health(url, wait_s)

    def msiexec_(p, what, args, log_name):
        if args[0] == "/fa":
            broken["on"] = False
            fake.calls.append(f"/fa {args[1]}")
            return 0
        return msiexec(p, what, args, log_name)
    monkeypatch.setattr(fake, "health", health_)
    monkeypatch.setattr(fake, "msiexec", msiexec_)
    rc, res = _go(monkeypatch, plan, fake)
    assert res["state"] == "rolled_back" and "msiexec exit -1" in res["reason"], res
    assert [c for c in fake.calls if c.startswith("/")] == [f"/i {plan['msi']}", f"/fa {plan['previous_msi']}"]
    assert res["health_version"] == "0.9.1" and res["resumed"] == ["engineer.a"]


# ------------------------------------------------------------------ t-fb8b63874e: what the owner's real update met

def test_the_update_ends_each_parked_seat_then_stops_code_by_its_own_command_then_strays_by_pid(monkeypatch, plan,
                                                                                                    tmp_path):
    """The owner's update rolled back: `stop --force` left the opt-in code server and the seats' feed monitors
    running from the install folder (architect m-4e2fe95fac). After the stop: each parked seat's recorded shell is
    ended with its tree (the feed monitor is its child), so the pool resumes it once into one fresh shell; a pid
    that is now another process is left alone; the code server is stopped by `heronry stop code` and started again
    after the relaunch; anything still running from the install folder is stopped by its own pid, never /T."""
    inst = plan["install_dir"]
    procs = [{"pid": 4101, "name": "heronry.exe", "image": f"{inst}/heronry.exe",
              "cmdline": f'"{inst}/heronry.exe" --heronry-service code-guard --port 19410'},
             {"pid": 4102, "name": "heronry.exe", "image": f"{inst}/heronry.exe",
              "cmdline": f'"{inst}/heronry.exe" -m edp8.feed_driver --participant orphan.x --board http://x'}]
    fake = Fake(tmp_path)
    real_fake_run = fake.run

    def run(p, what, argv, timeout=0):
        if what == "stop code":
            procs[:] = [x for x in procs if "code-guard" not in x["cmdline"]]
        return real_fake_run(p, what, argv, timeout)
    monkeypatch.setattr(fake, "run", run)
    parked = uh.Parked(["engineer.a", "qa.b"])
    parked.procs = {"engineer.a": {"pid": 5001, "create_time": 1000.0, "name": "claude.exe"},
                    "qa.b": {"pid": 5002, "create_time": 2000.0, "name": "claude.exe"}}
    monkeypatch.setattr(uh, "_proc_identity", lambda pid: {5001: (1000.3, "C:/x/claude.exe"),
                                                           5002: (9999.0, "C:/x/claude.exe")}.get(pid))
    monkeypatch.setattr(uh, "_cmdline", lambda pid: "claude --resume abc" if pid == 5001 else "")
    kills: list[list[str]] = []
    real_run = uh.subprocess.run
    monkeypatch.setattr(uh.subprocess, "run", lambda argv, **kw: kills.append(list(argv)) if argv[0] == "taskkill"
                        else real_run(argv, **kw))
    rc, res = _go(monkeypatch, plan, fake, procs=procs, park=lambda p: parked)
    assert res["state"] == "ok" and res["parked"] == res["resumed"] == ["engineer.a", "qa.b"]
    assert kills == [["taskkill", "/F", "/T", "/PID", "5001"], ["taskkill", "/F", "/PID", "4102"]]
    calls = fake.calls
    assert calls.index("stop") < calls.index("stop code") < calls.index("start") < calls.index("start code"), calls
    log = Path(plan["log"]).read_text(encoding="utf-8")
    assert "ending parked seat engineer.a: claude.exe (pid 5001)" in log
    assert "parked seat qa.b: pid 5002 is now another process" in log
    assert "stopping heronry.exe (pid 4102)" in log and "orphan.x" in log


def test_holders_retries_a_transient_failure_and_a_list_that_changed(monkeypatch):
    """The owner's helper logged `holders: None` and nothing else. Each look's return codes are logged now, and a
    failed call or a list that grew between the two RmGetList calls (234 again) is looked at again."""
    looks = iter([(None, {"start": 0, "register": [0], "list1": 234, "need": 3, "list2": 234}),
                  (None, {"start": 5}),
                  (["Heronry CLI (pid 7)"], {"start": 0, "register": [0], "list1": 234, "need": 1, "list2": 0})])
    monkeypatch.setattr(uh, "_rm_look", lambda folder, limit, images_only: next(looks))
    lines: list[str] = []
    assert uh.holders("C:/inst", images_only=True, log=lines.append, pause_s=0) == ["Heronry CLI (pid 7)"]
    assert len(lines) == 3 and "'list2': 234" in lines[0] and "'start': 5" in lines[1]
    monkeypatch.setattr(uh, "_rm_look", lambda folder, limit, images_only: (None, {"start": 5}))
    assert uh.holders("C:/inst", log=lines.append, tries=3, pause_s=0) is None  # None only after every try


def test_a_rollback_for_held_files_names_each_holder_without_token_values(monkeypatch, plan, tmp_path):
    secret = "Zk3" * 12
    monkeypatch.setattr(uh, "_cmdline", lambda pid: f'"C:/inst/heronry.exe" -m edp8.feed_driver --participant '
                                                    f'qa.e1 --token {secret} --api-key={secret}' if pid == 42 else "")
    fake = Fake(tmp_path, held=["Heronry CLI (pid 42)"])
    rc, res = _go(monkeypatch, plan, fake)
    assert res["state"] == "rolled_back"
    assert "Heronry CLI (pid 42): " in res["reason"] and "edp8.feed_driver --participant qa.e1" in res["reason"]
    assert secret not in res["reason"] and secret not in Path(plan["log"]).read_text(encoding="utf-8")


def test_park_keeps_each_parked_seats_process_fingerprint_from_the_pool(monkeypatch, plan):
    """The shell the update ends is the one the pool recorded at park time, read before the pool stops."""
    fp = {"pid": 5001, "create_time": 1000.0, "name": "claude.exe"}
    rows = [{"handle": "engineer.a", "state": "active", "proc": fp}, {"handle": "qa.b", "state": "parked", "proc": None}]
    monkeypatch.setattr(uh, "_http", lambda url, method="GET", **kw: rows if url.endswith("/v1/sessions") else {"parked": True})
    Path(plan["log"]).touch()
    got = uh._park(plan)
    assert list(got) == ["engineer.a"] and got.procs == {"engineer.a": fp} and got.failed == []


def test_the_backstop_spares_a_feed_monitor_whose_seat_lives_and_the_update_rolls_back_naming_the_seat(
        monkeypatch, plan, tmp_path):
    """Architect m-95b5fe285e: a live seat the update did not park (the pool did not track it) keeps its feed
    monitor, its only wake plane. The monitor is never stopped; the update installs nothing and names the seat."""
    inst = plan["install_dir"]
    procs = [{"pid": 4102, "name": "heronry.exe", "image": f"{inst}/heronry.exe",
              "cmdline": f'"{inst}/heronry.exe" -m edp8.feed_driver --participant architect.e1 --board http://x'}]
    seat = {"pid": 5980, "name": "claude.exe", "image": "C:/x/claude.exe", "cmdline": "claude --resume abc"}
    kills: list[list[str]] = []
    real_run = uh.subprocess.run
    monkeypatch.setattr(uh.subprocess, "run", lambda argv, **kw: kills.append(list(argv)) if argv[0] == "taskkill"
                        else real_run(argv, **kw))
    fake = Fake(tmp_path, held=["Heronry CLI (pid 4102)"])
    rc, res = _go(monkeypatch, plan, fake, procs=procs, seats={4102: seat})
    assert kills == [], "a seat's feed monitor is never stopped on its own"
    assert res["state"] == "rolled_back" and "claude.exe (pid 5980): claude --resume abc" in res["reason"]
    assert "Close this window, or resume the seat through the board" in res["reason"]
    assert not [c for c in fake.calls if c.startswith("/")], "nothing was installed"
    assert "sparing the feed monitor pid 4102" in Path(plan["log"]).read_text(encoding="utf-8")


def test_the_seat_above_a_feed_is_found_through_its_shells_and_a_reused_parent_pid_is_not_a_parent(monkeypatch):
    table = {10: (11, "heronry.exe"), 11: (12, "bash.exe"), 12: (13, "claude.exe"), 13: (1, "heronry.exe"),
             1: (0, "System"),
             20: (21, "heronry.exe"), 21: (1, "claude.exe"),   # 21 started after its child: a reused pid
             30: (31, "heronry.exe"), 31: (1, "heronry.exe")}  # a codex seat
    born = {10: 500.0, 11: 400.0, 12: 300.0, 13: 100.0, 1: 0.0, 20: 500.0, 21: 900.0, 30: 500.0, 31: 400.0}
    monkeypatch.setattr(uh, "_proc_identity", lambda pid: (born[pid], f"C:/x/{table[pid][1]}") if pid in born else None)
    monkeypatch.setattr(uh, "_cmdline", lambda pid: "heronry.exe -m edp8.codex_seat.run --handle adversary.e1"
                        if pid == 31 else "")
    assert uh._seat_above(10, table)["pid"] == 12
    assert uh._seat_above(20, table) is None
    assert uh._seat_above(30, table)["pid"] == 31


def test_update_refuses_up_front_naming_a_live_seat_the_pool_does_not_track(monkeypatch, tmp_path):
    """Architect m-95b5fe285e: before anything is downloaded, parked or stopped, `heronry update` refuses while a
    live seat outside the pool's active rows runs a feed monitor from the install folder, and names it."""
    from edp8 import updater
    monkeypatch.setattr(updater, "foreign_dirs", lambda: [])
    monkeypatch.setattr(updater, "install_scope_busy", lambda: False)
    monkeypatch.setattr(updater, "update_staged", lambda: False)
    monkeypatch.setattr(updater, "current_version", lambda: "0.9.1")
    monkeypatch.setattr(updater, "fetch_msi_release", lambda url, tag=None: updater.Release("0.9.2", {}, {}))
    monkeypatch.setattr(updater, "download", lambda rel: pytest.fail("a refused update downloads nothing"))
    monkeypatch.setattr(updater, "_owned_endpoints", lambda launcher: {"pool_ours": True, "pool_url": "http://pool"})
    monkeypatch.setattr(uh, "_park", lambda p: pytest.fail("a refused update parks nothing"))
    monkeypatch.setattr(uh, "_http", lambda url, *a, **kw: [{"handle": "engineer.a", "state": "active",
                                                            "proc": {"pid": 100}},
                                                           {"handle": "architect.e1", "state": "done",
                                                            "proc": {"pid": 999}}])
    feed = {"pid": 7, "name": "heronry.exe", "image": "x", "cmdline": "heronry.exe -m edp8.feed_driver"}
    monkeypatch.setattr(uh, "seat_feeds", lambda folder, ps=None: [
        {"feed": feed, "seat": {"pid": 100, "name": "claude.exe", "cmdline": "claude"}},
        {"feed": feed, "seat": {"pid": 5980, "name": "claude.exe", "cmdline": "claude --resume abc"}}], raising=False)
    with pytest.raises(updater.UpdateError) as e:
        updater.apply_msi({"release-url": str(tmp_path)})
    msg = str(e.value)
    assert "claude.exe (pid 5980): claude --resume abc" in msg and "pid 100" not in msg
    assert "Close this window, or resume the seat through the board, then run update again" in msg
    assert "Nothing changed" in msg


def test_msiexec_gets_each_property_value_quoted_never_the_whole_token(monkeypatch, tmp_path):
    """t-fd7cf3a6b5: the owner's update into the default folder (Heronry contributors/Heronry Desktop) exited 1639.
    A list argv made subprocess quote the whole `INSTALLFOLDER=<dir>` token, a form msiexec refuses; it wants
    `PROP="value"`. The install and the rollback reinstall share these args, so both get the same command line."""
    inst = tmp_path / "Programs" / "Heronry contributors" / "Heronry Desktop"
    msi = tmp_path / "update dir" / "Heronry Desktop-0.10.1.msi"
    plan = {"install_dir": str(inst), "log": str(tmp_path / "log dir" / "update.log")}
    seen = []
    monkeypatch.setattr(uh.subprocess, "run", lambda cmd, **kw: seen.append(cmd) or type("R", (), {"returncode": 0})())
    assert uh._msiexec(plan, "install", uh._msi_install_args(plan, str(msi)), "msiexec-install.log") == 0
    mlog = tmp_path / "log dir" / "msiexec-install.log"
    assert seen == [f'msiexec /i "{msi}" MSIINSTALLPERUSER="1" ALLUSERS="2" INSTALLFOLDER="{inst}" '
                    f'REBOOT="ReallySuppress" /qn /norestart /l*v "{mlog}"']
    assert uh.msi_cmdline(["/x", "{0A1B-2C3D}"]) == 'msiexec /x "{0A1B-2C3D}"'
    assert uh.msi_cmdline(["/a", str(msi), "/qn", f"TARGETDIR={inst}"]) == \
        f'msiexec /a "{msi}" /qn TARGETDIR="{inst}"'
    with pytest.raises(ValueError):
        uh.msi_cmdline(["/i", 'C:\a"b.msi'])
    # a trailing backslash would escape the closing quote (m-eab86ba45f): dropped from a folder, a drive root refused
    assert uh.msi_cmdline(["/a", str(msi), f"TARGETDIR={inst}\\"]) == f'msiexec /a "{msi}" TARGETDIR="{inst}"'
    for root in ("C:\\", "d:\\\\"):
        with pytest.raises(ValueError):
            uh.msi_cmdline(["/a", str(msi), f"TARGETDIR={root}"])


@pytest.mark.skipif(__import__("sys").platform != "win32", reason="Windows Installer")
def test_the_real_msiexec_parses_the_command_line_for_an_install_folder_with_spaces(tmp_path):
    """The real msiexec, on a package that does not exist: 1619 (package could not be opened) means it parsed the
    command line; 1639 (invalid command line) is the owner's failure. No install is attempted either way."""
    inst = tmp_path / "Heronry contributors" / "Heronry Desktop"
    plan = {"install_dir": str(inst), "log": str(tmp_path / "log dir" / "update.log")}
    (tmp_path / "log dir").mkdir()
    rc = uh._msiexec(plan, "install", uh._msi_install_args(plan, str(tmp_path / "no such dir" / "none.msi")),
                     "msiexec-install.log")
    assert rc == 1619, rc
