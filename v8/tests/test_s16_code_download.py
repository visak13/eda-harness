"""S16 (s-df7bb16c33) C3: `heronry start code` downloads the pinned standalone code-server, so a Windows host needs
no node, npm or python on PATH.

The 217 MB release is never fetched here: a synthetic tarball (the same shape, `<server_dir>/lib/node.exe`) stands in,
its sha256 is the pin, and the downloader (`code_service._FETCH`) is replaced by a function that writes it.
"""

from __future__ import annotations

import hashlib
import io
import json
import re
import sys
import tarfile
import time
from pathlib import Path

import pytest

from edp8 import code_service

V8 = Path(__file__).resolve().parents[1]
SERVER_DIR = "code-server-9.9.9-windows-amd64"


# the MSI / Win32 update path (msiexec, ctypes.windll): Windows-only code, so Windows-only tests
WINDOWS_ONLY = pytest.mark.skipif(sys.platform != "win32", reason="Windows-only (MSI / Win32 API)")


def _tar(path: Path, members: dict[str, bytes]) -> str:
    with tarfile.open(path, "w:gz") as tf:
        for name, data in members.items():
            ti = tarfile.TarInfo(name)
            ti.size = len(data)
            tf.addfile(ti, io.BytesIO(data))
    return hashlib.sha256(path.read_bytes()).hexdigest()


@pytest.fixture
def pin(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    for k in ("EDP_CODE_SERVER_PATH", "EDP_CODE_DATA"):
        monkeypatch.delenv(k, raising=False)
    empty = tmp_path / "emptybin"
    empty.mkdir()
    monkeypatch.setenv("PATH", str(empty))  # no code-server (this machine has an npm one), node, npm or python on PATH
    monkeypatch.setenv("EDP_HOME", str(tmp_path / "home"))
    monkeypatch.setenv("EDP_CODE_DATA", str(tmp_path / "data" / "code"))
    good = tmp_path / "good.tar.gz"
    sha = _tar(good, {f"{SERVER_DIR}/lib/node.exe": b"MZ-node", f"{SERVER_DIR}/package.json": b'{"version": "9.9.9"}'})
    lock = {"version": "9.9.9", "asset": "code-server-9.9.9-windows-amd64.tar.gz", "size": good.stat().st_size,
            "url": "https://example.invalid/code-server.tar.gz", "sha256": sha, "server_dir": SERVER_DIR,
            "node": "lib/node.exe"}
    monkeypatch.setattr(code_service, "pinned_download", lambda: dict(lock))
    calls: list[str] = []

    def fetch(url, part, size, say):
        calls.append(url)
        part.write_bytes(good.read_bytes())
    monkeypatch.setattr(code_service, "_FETCH", fetch)
    return {"lock": lock, "calls": calls, "good": good, "root": tmp_path / "data" / "code"}


def test_ensure_pinned_downloads_verifies_unpacks_and_runs_with_the_bundled_node(pin):
    say: list[str] = []
    inst = code_service.ensure_pinned(say.append)
    dest = pin["root"] / "server" / "9.9.9"
    assert pin["calls"] == [pin["lock"]["url"]]
    assert inst.source == "download" and inst.version == "9.9.9" and inst.sha256 == pin["lock"]["sha256"]
    # the bundled node runs the release dir: no `node`, `npm` or `python` looked up by name
    assert inst.argv == [str(dest / SERVER_DIR / "lib" / "node.exe"), str(dest / SERVER_DIR)]
    assert (dest / ".verified").read_text(encoding="ascii") == pin["lock"]["sha256"]
    assert not (pin["root"] / "server" / "9.9.9.tmp").exists()
    assert not (pin["root"] / "download" / pin["lock"]["asset"]).exists()  # the tarball is not kept
    assert any("sha256 verified" in m for m in say)


def test_second_call_and_locate_reuse_the_unpacked_release(pin):
    code_service.ensure_pinned()
    assert code_service.locate().source == "download"
    code_service.ensure_pinned()
    assert len(pin["calls"]) == 1


def test_a_sha_mismatch_unpacks_nothing_and_deletes_the_download(pin, tmp_path, monkeypatch):
    bad = tmp_path / "bad.tar.gz"
    _tar(bad, {f"{SERVER_DIR}/lib/node.exe": b"tampered"})
    monkeypatch.setattr(code_service, "_FETCH", lambda url, part, size, say: part.write_bytes(bad.read_bytes()))
    with pytest.raises(code_service.CodeError, match="sha256 mismatch.*nothing was unpacked"):
        code_service.ensure_pinned()
    assert not (pin["root"] / "server").exists()
    assert list((pin["root"] / "download").iterdir()) == []
    assert code_service.locate() is None


def test_an_archive_that_escapes_the_target_is_refused(pin, tmp_path, monkeypatch):
    evil = tmp_path / "evil.tar.gz"
    sha = _tar(evil, {f"{SERVER_DIR}/lib/node.exe": b"x", "../escaped.txt": b"zip-slip"})
    monkeypatch.setattr(code_service, "pinned_download", lambda: {**pin["lock"], "sha256": sha})
    monkeypatch.setattr(code_service, "_FETCH", lambda url, part, size, say: part.write_bytes(evil.read_bytes()))
    with pytest.raises(code_service.CodeError, match="could not unpack"):
        code_service.ensure_pinned()
    assert not (pin["root"] / "server" / "escaped.txt").exists() and not (pin["root"] / "escaped.txt").exists()
    assert not (pin["root"] / "server" / "9.9.9").exists() and not (pin["root"] / "server" / "9.9.9.tmp").exists()


def test_an_archive_without_the_bundled_node_is_refused(pin, tmp_path, monkeypatch):
    odd = tmp_path / "odd.tar.gz"
    sha = _tar(odd, {f"{SERVER_DIR}/package.json": b"{}"})
    monkeypatch.setattr(code_service, "pinned_download", lambda: {**pin["lock"], "sha256": sha})
    monkeypatch.setattr(code_service, "_FETCH", lambda url, part, size, say: part.write_bytes(odd.read_bytes()))
    with pytest.raises(code_service.CodeError, match="has no .*node.exe"):
        code_service.ensure_pinned()
    assert code_service.locate() is None


def test_a_cached_archive_with_the_right_hash_skips_the_network(pin):
    cache = pin["root"] / "download"
    cache.mkdir(parents=True)
    (cache / pin["lock"]["asset"]).write_bytes(pin["good"].read_bytes())
    code_service.ensure_pinned()
    assert pin["calls"] == []


def test_status_says_the_first_start_downloads_and_is_not_an_error(pin):
    st = code_service.status()
    assert st["state"] == "down" and st["installed"] is False and st["downloadable"] is True
    assert "downloads the pinned code-server 9.9.9" in st["install_hint"] and "npm" not in st["install_hint"].lower()


def test_start_downloads_a_missing_code_server_then_launches_it(pin, monkeypatch):
    seen: list[str] = []

    def fake_ensure(say=None):
        seen.append("ensure")
        raise code_service.CodeError("stop here: the launch path is proven by test_code_service_py")
    monkeypatch.setattr(code_service, "ensure_pinned", fake_ensure)
    monkeypatch.setattr(code_service, "_listening", lambda p: False)
    with pytest.raises(code_service.CodeError, match="stop here"):
        code_service.start()
    assert seen == ["ensure"]


def test_the_pin_is_validated(tmp_path, monkeypatch):
    bad = tmp_path / "lock.json"
    bad.write_text(json.dumps({"version": "1.2.3", "asset": "a", "url": "http://insecure/x", "size": 1,
                               "sha256": "0" * 64, "server_dir": "d", "node": "lib/node.exe"}), encoding="utf-8")
    monkeypatch.setattr(code_service, "_lock_files", lambda: [bad])
    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.setattr("platform.machine", lambda: "AMD64")
    assert code_service.pinned_download() is None  # http, not https


def test_the_real_lock_is_a_valid_https_pin_and_ships_in_the_wheel():
    lock = json.loads((V8 / "vscode-ext" / "code-server.lock.json").read_text(encoding="utf-8"))
    assert lock["url"].startswith("https://") and re.fullmatch(r"[0-9a-f]{64}", lock["sha256"])
    py = (V8 / "pyproject.toml").read_text(encoding="utf-8")
    assert '"vscode-ext/code-server.lock.json" = "edp8/code_server.lock.json"' in py


def test_no_npm_install_hint_for_code_server_remains():
    pat = re.compile(r"npm\s+(install|i)\s+(-g|--global)\s+code-server", re.I)
    hits = []
    for root in ("src", "web/src", "guides", "scripts", "vscode-ext/edp-code/src"):
        for f in (V8 / root).rglob("*"):
            if f.is_file() and f.suffix in {".py", ".ts", ".tsx", ".md", ".ps1", ".json"} and "node_modules" not in f.parts:
                if pat.search(f.read_text(encoding="utf-8", errors="replace")):
                    hits.append(str(f.relative_to(V8)))
    readme = V8 / "README.md"
    if pat.search(readme.read_text(encoding="utf-8")):
        hits.append("README.md")
    # this file names the pattern in its regex only (no literal command)
    assert hits == [], hits


@WINDOWS_ONLY
def test_no_download_opt_out_makes_a_missing_code_server_not_installed(tmp_path, monkeypatch):
    empty = tmp_path / "emptybin"
    empty.mkdir()
    monkeypatch.setenv("PATH", str(empty))
    monkeypatch.delenv("EDP_CODE_SERVER_PATH", raising=False)
    monkeypatch.setenv("EDP_HOME", str(tmp_path / "home"))
    monkeypatch.setenv("EDP_CODE_DATA", str(tmp_path / "code"))
    monkeypatch.setenv("EDP_CODE_NO_DOWNLOAD", "1")
    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.setattr("platform.machine", lambda: "AMD64")
    assert code_service.pinned_download() is None
    st = code_service.status()
    assert st["state"] == "not_installed" and st["downloadable"] is False and "code_server.path" in st["install_hint"]


def test_the_downloader_streams_https_reports_progress_and_wraps_network_errors(tmp_path, monkeypatch):
    import urllib.error

    class Resp(io.BytesIO):
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    monkeypatch.setattr(code_service.urllib.request, "urlopen", lambda req, timeout=0: Resp(b"x" * (3 << 20)))
    said: list[str] = []
    part = tmp_path / "a.part"
    code_service._http_fetch("https://example.invalid/a", part, 3 << 20, said.append)
    assert part.stat().st_size == 3 << 20 and any("100%" in m for m in said)
    with pytest.raises(code_service.CodeError, match="must be https"):
        code_service._http_fetch("http://example.invalid/a", part, 1, said.append)

    def boom(req, timeout=0):
        raise urllib.error.URLError("no route")
    monkeypatch.setattr(code_service.urllib.request, "urlopen", boom)
    with pytest.raises(code_service.CodeError, match="could not download code-server"):
        code_service._http_fetch("https://example.invalid/a", part, 1, said.append)


def test_the_downloader_stops_one_byte_past_the_pinned_size(tmp_path, monkeypatch):
    """review m-1775486e17 #4: a server that sends more than the pin says is cut off, not read to the end."""
    class Endless(io.RawIOBase):
        served = 0

        def read(self, n=-1):
            Endless.served += n
            return b"x" * n

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    monkeypatch.setattr(code_service.urllib.request, "urlopen", lambda req, timeout=0: Endless())
    part = tmp_path / "big.part"
    with pytest.raises(code_service.CodeError, match="larger than the pinned"):
        code_service._http_fetch("https://example.invalid/a", part, 5, lambda _m: None)
    assert Endless.served == 6 and part.stat().st_size == 6  # size + 1, no more


# ---------------------------------------------------------------- RC2 item 2 (t-e338298d88): a broken code-server on PATH

def _path_code_server(pin, body: str) -> Path:
    """A code-server on PATH (a .bat, as an npm shim is a .cmd): `body` is what it does when run."""
    shim = Path(pin["root"]).parents[1] / "emptybin" / "code-server.bat"
    shim.write_text("@echo off\r\n" + body + "\r\n", encoding="ascii")
    code_service._PROBED.clear()
    return shim


@pytest.mark.skipif(sys.platform != "win32", reason="a .bat code-server shim")
def test_a_broken_code_server_on_path_falls_through_to_the_pinned_download(pin, monkeypatch):
    _path_code_server(pin, "echo node: not found 1>&2\r\nexit /b 1")
    assert code_service.locate() is None  # found on PATH, but it does not run: passed over
    st = code_service.status()
    assert st["installed"] is False and st["downloadable"] is True and st["state"] == "down"
    seen: list[str] = []

    def fake_ensure(say=None):
        seen.append("ensure")
        raise code_service.CodeError("stop here: the launch path is proven by test_code_service_py")
    monkeypatch.setattr(code_service, "ensure_pinned", fake_ensure)
    monkeypatch.setattr(code_service, "_listening", lambda p: False)
    with pytest.raises(code_service.CodeError, match="stop here"):
        code_service.start()
    assert seen == ["ensure"]


@pytest.mark.skipif(sys.platform != "win32", reason="a .bat code-server shim")
def test_a_working_code_server_on_path_is_used_with_its_version(pin, monkeypatch):
    shim = _path_code_server(pin, "echo 4.99.1 0123abcd with Code 1.99.0")
    inst = code_service.locate()
    assert inst is not None and inst.source == "path" and inst.version == "4.99.1"
    from edp_contracts import proc
    calls: list[list[str]] = []
    orig = proc.run_bounded
    monkeypatch.setattr(proc, "run_bounded", lambda argv, *a, **kw: calls.append(argv) or orig(argv, *a, **kw))
    assert code_service.locate().version == "4.99.1" and calls == []  # a status poll never re-runs the probe
    shim.write_text("@echo off\r\nexit /b 1\r\n", encoding="ascii")  # the shim changed: probed again
    assert code_service.locate() is None and calls


@pytest.mark.skipif(sys.platform != "win32", reason="a .bat code-server shim")
def test_a_hung_code_server_on_path_is_passed_over(pin, monkeypatch):
    monkeypatch.setattr(code_service, "_PROBE_RUN_S", 1.0)
    _path_code_server(pin, "ping -n 30 127.0.0.1 >nul")
    t0 = time.monotonic()
    assert code_service.locate() is None
    assert time.monotonic() - t0 < 5.0  # D9: the shim's ping held the pipe until it exited (30 s)
