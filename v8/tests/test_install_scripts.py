"""install.sh / install.ps1 pass every path as ONE argument when temp, home and release paths hold spaces
or an apostrophe (S11 F8, t-55932804e2).

Each test runs the real installer against local hash-verified fixture wheels, with a fake `uv` and a fake
`heronry` first on PATH that record their argv; nothing is installed and the fleet is not touched.
"""
import hashlib
import os
import shutil
import subprocess
import sys
from pathlib import Path
from urllib.parse import unquote, urlparse

import pytest

ROOT = Path(__file__).resolve().parents[2]
WHEELS = ("edp8", "edp_contracts", "edp_pool", "edp_broker")
SIBLINGS = [w for w in WHEELS if w != "edp8"]
END = "--END--"


def _layout(tmp_path):
    base = tmp_path / "it's here"
    rel, temp, home, bin_dir = base / "release dir", base / "temp with spaces", base / "home dir", tmp_path / "bin"
    for p in (rel, temp, home, bin_dir):
        p.mkdir(parents=True)
    sums = []
    for dist in WHEELS:
        name = f"{dist}-9.0.0-py3-none-any.whl"
        (rel / name).write_bytes(b"harmless fixture " + dist.encode())
        sums.append(f"{hashlib.sha256((rel / name).read_bytes()).hexdigest()}  {name}\n")
    (rel / "SHA256SUMS").write_text("".join(sums), newline="\n")
    return rel, temp, home, bin_dir


def _calls(log):
    calls, cur = [], []
    for line in log.read_text().splitlines():
        if line == END:
            calls.append(cur)
            cur = []
        else:
            cur.append(line)
    return calls


def _check_install(calls, embed):
    installs = [c for c in calls if c[:2] == ["tool", "install"]]
    assert len(installs) == 1, calls
    argv = installs[0]
    assert argv[2:5] == ["--force", "--python", "3.12"], argv
    spec, rest = argv[5], argv[6:]
    if embed:
        head, _, url = spec.partition(" @ ")
        assert head == "edp8[embed]" and url.startswith("file:///") and " " not in url, spec
        path = unquote(urlparse(url).path)
        assert "temp with spaces" in path and path.endswith("/edp8-9.0.0-py3-none-any.whl"), path
    else:
        assert "temp with spaces" in spec and spec.replace("\\", "/").endswith("/edp8-9.0.0-py3-none-any.whl"), spec
    # exactly one --with <path> pair per sibling wheel: a split path would add stray arguments
    assert len(rest) == 2 * len(SIBLINGS), argv
    for i, dist in enumerate(SIBLINGS):
        flag, path = rest[2 * i], rest[2 * i + 1]
        assert flag == "--with", argv
        assert "temp with spaces" in path and path.replace("\\", "/").endswith(f"/{dist}-9.0.0-py3-none-any.whl"), path


# -- install.sh ------------------------------------------------------------------------------------------

def _sh():
    if sys.platform != "win32":
        return shutil.which("sh")
    git = Path("C:/Program Files/Git/bin/sh.exe")   # never WSL's bash.exe from System32
    return str(git) if git.exists() else None


def _posix(p):
    s = str(Path(p).resolve()).replace("\\", "/")
    return "/" + s[0].lower() + s[2:] if sys.platform == "win32" else s


FAKE_SH = """#!/bin/sh
case "$*" in
  "--version") echo "uv 0.9.11"; exit 0 ;;
  "tool dir --bin --color never") printf '%s\\n' "$S11_BIN"; exit 0 ;;
  "version") echo "heronry 0.0.1"; exit 0 ;;
esac
{ printf '%s\\n' "$@"; echo "--END--"; } >> "$S11_LOG"
"""


@pytest.mark.parametrize("embed", [False, True], ids=["no-embed", "embed"])
def test_install_sh_passes_each_wheel_path_as_one_argument(tmp_path, embed):
    sh = _sh()
    if not sh:
        pytest.skip("no POSIX sh (Git Bash on Windows) to run install.sh")
    rel, temp, home, bin_dir = _layout(tmp_path)
    for name in ("uv", "heronry"):
        (bin_dir / name).write_text(FAKE_SH, newline="\n")
        (bin_dir / name).chmod(0o755)
    log = tmp_path / "argv.log"
    env = {k: v for k, v in os.environ.items() if not k.startswith(("EDP", "HERONRY"))}
    env.update(PATH=_posix(bin_dir) + ":/usr/bin:/bin", TMPDIR=_posix(temp), HOME=_posix(home),
               S11_BIN=_posix(bin_dir), S11_LOG=_posix(log))
    argv = [sh, str(ROOT / "install.sh"), "--release-url", _posix(rel), "--no-modify-path", "--yes"]
    if not embed:
        argv.append("--no-embed")
    r = subprocess.run(argv, env=env, capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, r.stdout + r.stderr
    calls = _calls(log)
    _check_install(calls, embed)
    assert calls[-1] == ["prereqs", "install", "--yes"] + ([] if embed else ["--no-embed"]), calls
    assert not any(temp.iterdir()), "the work dir is removed"


# -- install.ps1 -----------------------------------------------------------------------------------------

FAKE_CS = r"""
using System; using System.IO;
public static class Fake {
  public static int Main(string[] a) {
    string all = String.Join(" ", a);
    if (all == "--version") { Console.WriteLine("uv 0.9.11"); return 0; }
    if (all == "tool dir --bin --color never") { Console.WriteLine(Environment.GetEnvironmentVariable("S11_BIN")); return 0; }
    if (all == "version") { Console.WriteLine("heronry 0.0.1"); return 0; }
    File.AppendAllText(Environment.GetEnvironmentVariable("S11_LOG"), String.Join("\n", a) + "\n--END--\n");
    return 0;
  }
}
"""


@pytest.fixture(scope="module")
def fake_exe(tmp_path_factory):
    if sys.platform != "win32" or not shutil.which("powershell"):
        pytest.skip("install.ps1 runs under Windows PowerShell")
    d = tmp_path_factory.mktemp("fakeexe")
    (d / "fake.cs").write_text(FAKE_CS)
    out = d / "fake.exe"
    ps = (f"Add-Type -TypeDefinition (Get-Content -Raw -LiteralPath '{d / 'fake.cs'}') "
          f"-OutputAssembly '{out}' -OutputType ConsoleApplication")
    r = subprocess.run(["powershell", "-NoProfile", "-Command", ps], capture_output=True, text=True, timeout=120)
    assert out.exists(), r.stdout + r.stderr
    return out


@pytest.mark.parametrize("embed", [False, True], ids=["no-embed", "embed"])
def test_install_ps1_passes_each_wheel_path_as_one_argument(tmp_path, fake_exe, embed):
    rel, temp, home, bin_dir = _layout(tmp_path)
    for name in ("uv.exe", "heronry.exe"):
        shutil.copy(fake_exe, bin_dir / name)
    log = tmp_path / "argv.log"
    env = {k: v for k, v in os.environ.items() if not k.startswith(("EDP", "HERONRY"))}
    env.update(PATH=f"{bin_dir};{os.environ['SystemRoot']}\\System32;{os.environ['SystemRoot']}\\System32\\WindowsPowerShell\\v1.0",
               TEMP=str(temp), TMP=str(temp), USERPROFILE=str(home), S11_BIN=str(bin_dir), S11_LOG=str(log))
    argv = ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(ROOT / "install.ps1"),
            "-ReleaseUrl", str(rel), "-NoModifyPath", "-Yes"]
    if not embed:
        argv.append("-NoEmbed")
    r = subprocess.run(argv, env=env, capture_output=True, text=True, timeout=120)
    assert r.returncode == 0, r.stdout + r.stderr
    calls = _calls(log)
    _check_install(calls, embed)
    assert calls[-1] == ["prereqs", "install", "--yes"] + ([] if embed else ["--no-embed"]), calls
    assert not any(temp.iterdir()), "the work dir is removed"


# -- v0.9.1 (s-dbe96f11cd): `irm <url>/install.ps1 | iex` on Windows PowerShell 5.1 ---------------------------
# 0.9.0 shipped install.ps1 with a UTF-8 BOM. irm hands iex the body as text; the BOM arrives as stray
# characters ahead of the first comment, so `param(...)` is no longer the script's first statement and 5.1
# fails at `[string]$Version`. The script ships without a BOM and ASCII-only (no encoding to guess).


def test_install_ps1_has_no_bom_and_is_ascii():
    raw = (ROOT / "install.ps1").read_bytes()
    assert not raw.startswith(b"\xef\xbb\xbf"), "install.ps1 must not start with a UTF-8 BOM"
    bad = [i for i, b in enumerate(raw) if b > 0x7F]
    assert not bad, f"non-ASCII byte at offset {bad[0]}"


def test_install_ps1_parses_as_irm_hands_it_to_iex():
    if sys.platform != "win32" or not shutil.which("powershell"):
        pytest.skip("Windows PowerShell 5.1 only")
    # irm decodes a body served without a charset as ISO-8859-1; iex then parses that string. Parsing it
    # through [ScriptBlock]::Create runs the same parser without executing anything.
    ps = ("$ErrorActionPreference='Stop'; "
          f"$s = [Text.Encoding]::GetEncoding(28591).GetString([IO.File]::ReadAllBytes('{ROOT / 'install.ps1'}')); "
          "$sb = [ScriptBlock]::Create($s); "
          "if (-not $sb.Ast.ParamBlock) { throw 'param block lost' }; "
          "'params: ' + (($sb.Ast.ParamBlock.Parameters | ForEach-Object { $_.Name.VariablePath.UserPath }) -join ',')")
    r = subprocess.run(["powershell", "-NoProfile", "-Command", ps], capture_output=True, text=True, timeout=120)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "params: Version,ReleaseUrl" in r.stdout, r.stdout
