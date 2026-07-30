"""W11 (DESIGN-v6) — foreground session capture: the hook + the reader.

Covers the surface built by action a4_foreground_capture_hook:

  * ``.claude/hooks/capture-session.py`` — the SessionStart hook that appends
    the FOREGROUND shell's ``session_id`` to ``<repo>/.sessions/foreground.jsonl``.
  * ``edp_claude.sessions.latest_foreground_session`` — the reader a5's
    ``suspend_recipe`` calls to render ``claude-personal --resume <id>``.
  * ``.claude/settings.json`` — the wiring, added as a SIBLING of the existing
    ``compact`` -> reground-on-compact.py entry (regression-guarded below).

Two tests here exist because a passing happy path would NOT have caught the
defects they cover:

  * ``test_pool_spawned_shell_is_not_captured`` — pool-spawned shells run under
    this same project's settings.json and fire this same hook. Ungated, the
    newest registry line would be a WORKER's session id and the resume command
    would reattach to the wrong shell. A gate whose refusal branch is never
    executed is not a gate, so this asserts the NEGATIVE.
  * ``test_hook_and_reader_resolve_the_same_log_path`` — the hook restates the
    log path instead of importing it (it stays stdlib-only to add no latency to
    session start). A silent drift between the two constants would leave the
    writer appending happily while the reader returned None forever.

Env discipline (d7/d8): pure Python, no POSIX shell. The hook is imported by
file path and driven in-process (stdin via ``io.StringIO``), so no external
process is spawned. Leaked worker env (EDP_ROLE/EDP_HANDLE) is neutralised
in-process — it would otherwise trip the hook's own foreground gate.
"""

import importlib.util
import io
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

from edp_claude import sessions

REPO = Path(__file__).resolve().parents[1]
HOOK_PATH = REPO / ".claude" / "hooks" / "capture-session.py"
SETTINGS_PATH = REPO / ".claude" / "settings.json"

_RECORD_KEYS = {"session_id", "cwd", "config_dir", "started_at"}


# ── env discipline: a leaked EDP_ROLE would make every capture test a no-op ───
@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    for var in ("EDP_ROLE", "EDP_HANDLE", "EDP_TIER_WRITE", "CLAUDE_CONFIG_DIR"):
        monkeypatch.delenv(var, raising=False)


# ── load the hyphenated hook script by file path (not importable by name) ─────
def _load_hook():
    assert HOOK_PATH.exists(), f"W11 hook missing at {HOOK_PATH}"
    spec = importlib.util.spec_from_file_location("capture_session", HOOK_PATH)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture
def hook():
    return _load_hook()


@pytest.fixture
def log_path(tmp_path):
    """A registry path whose .sessions/ parent does NOT yet exist."""
    return tmp_path / ".sessions" / "foreground.jsonl"


def _run_main(mod, monkeypatch, capsys, stdin_text, log_path):
    """Drive the hook's main() with `stdin_text` on stdin, writing to
    `log_path`; return (exit_code, captured) where `captured` carries .out/.err."""
    monkeypatch.setattr(sys, "stdin", io.StringIO(stdin_text))
    monkeypatch.setattr(mod, "FOREGROUND_LOG", log_path)
    rc = mod.main()
    return rc, capsys.readouterr()


def _payload(session_id="sess-abc123", cwd=str(REPO)):
    return json.dumps({
        "session_id": session_id,
        "cwd": cwd,
        "hook_event_name": "SessionStart",
        "source": "startup",
    })


# ── (a) a sample payload appends ONE well-formed line with all 4 keys ────────
def test_hook_appends_well_formed_record(hook, monkeypatch, capsys, log_path):
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", r"C:\Users\me\.claude-personal")
    rc, cap = _run_main(hook, monkeypatch, capsys, _payload(), log_path)

    assert rc == 0
    assert cap.out == ""  # stdout is the hook interface — must stay untouched
    assert cap.err == ""  # the happy path is silent
    lines = log_path.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 1
    record = json.loads(lines[0])
    assert set(record) == _RECORD_KEYS
    assert record["session_id"] == "sess-abc123"
    assert record["cwd"] == str(REPO)
    assert record["config_dir"] == r"C:\Users\me\.claude-personal"
    # started_at is a tz-aware UTC ISO timestamp
    started = datetime.fromisoformat(record["started_at"])
    assert started.tzinfo is not None
    assert started.utcoffset() == timezone.utc.utcoffset(None)


def test_config_dir_is_null_when_unset(hook, monkeypatch, capsys, log_path):
    """A plain `claude` launch has no CLAUDE_CONFIG_DIR; the key is still
    written (as null) so the reader can tell "absent" from "never captured"."""
    rc, _cap = _run_main(hook, monkeypatch, capsys, _payload(), log_path)
    assert rc == 0
    record = json.loads(log_path.read_text(encoding="utf-8").strip())
    assert set(record) == _RECORD_KEYS
    assert record["config_dir"] is None


def test_hook_appends_never_truncates(hook, monkeypatch, capsys, log_path):
    """Append-only: /clear may reuse or replace the session id — either way no
    prior entry is lost."""
    for sid in ("sess-1", "sess-2", "sess-3"):
        _run_main(hook, monkeypatch, capsys, _payload(session_id=sid), log_path)
    lines = log_path.read_text(encoding="utf-8").splitlines()
    assert [json.loads(ln)["session_id"] for ln in lines] == \
        ["sess-1", "sess-2", "sess-3"]


# ── (b) crash-safety: malformed stdin → exit 0, nothing written ──────────────
@pytest.mark.parametrize("bad", ["{not json", "", "null", "[]", "\x00\x01",
                                 '"a string"', "12345"])
def test_hook_is_failsafe_on_malformed_input(hook, monkeypatch, capsys,
                                             log_path, bad):
    rc, cap = _run_main(hook, monkeypatch, capsys, bad, log_path)
    assert rc == 0, bad
    assert cap.out == "", bad  # never corrupt the stdout hook interface
    assert not log_path.exists(), bad


@pytest.mark.parametrize("payload", [
    {"source": "startup"},                       # no session_id at all
    {"session_id": "", "cwd": "/x"},             # empty session_id
    {"session_id": "   ", "cwd": "/x"},          # whitespace-only
    {"session_id": 12345, "cwd": "/x"},          # wrong type
])
def test_hook_writes_nothing_without_a_usable_session_id(hook, monkeypatch,
                                                         capsys, log_path,
                                                         payload):
    rc, cap = _run_main(hook, monkeypatch, capsys, json.dumps(payload), log_path)
    assert rc == 0
    assert cap.out == ""
    assert not log_path.exists()


def test_hook_exits_zero_even_when_the_log_is_unwritable(hook, monkeypatch,
                                                         capsys, tmp_path):
    """The highest-blast-radius guarantee: an unwritable registry must never
    break session start. Point the log at a path whose parent is a FILE.

    Asserts the fail-safe branch actually EXECUTED (it reports the cause on
    stderr) rather than the write having quietly succeeded — and that the
    exception is never swallowed silently."""
    blocker = tmp_path / "not-a-dir"
    blocker.write_text("", encoding="utf-8")
    rc, cap = _run_main(hook, monkeypatch, capsys, _payload(),
                        blocker / ".sessions" / "foreground.jsonl")
    assert rc == 0
    assert cap.out == ""  # the diagnostic goes to stderr, never stdout
    assert "could not record foreground session" in cap.err


# ── (c) the hook creates .sessions/ when it is missing ───────────────────────
def test_hook_creates_sessions_dir_when_absent(hook, monkeypatch, capsys,
                                               log_path):
    assert not log_path.parent.exists()
    rc, _cap = _run_main(hook, monkeypatch, capsys, _payload(), log_path)
    assert rc == 0
    assert log_path.parent.is_dir()
    assert log_path.is_file()


# ── the EDP_ROLE gate: pool-spawned shells must NOT be captured ──────────────
@pytest.mark.parametrize("role", ["worker", "planner", "reviewer"])
def test_pool_spawned_shell_is_not_captured(hook, monkeypatch, capsys,
                                            log_path, role):
    """pty_launcher.py stamps EDP_ROLE on every pool spawn, and those shells
    fire this same hook. Assert the NEGATIVE: nothing is written."""
    monkeypatch.setenv("EDP_ROLE", role)
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(REPO / ".claude-pool"))
    rc, cap = _run_main(hook, monkeypatch, capsys, _payload("worker-sid"),
                        log_path)
    assert rc == 0
    assert cap.out == ""
    assert not log_path.exists(), f"{role} shell polluted the registry"


def test_pool_spawned_shell_does_not_append_to_an_existing_registry(
        hook, monkeypatch, capsys, log_path):
    """The dangerous case: a real foreground entry already exists and a worker
    spawn must not become the LAST line."""
    log_path.parent.mkdir(parents=True)
    _run_main(hook, monkeypatch, capsys, _payload("real-foreground"), log_path)
    before = log_path.read_bytes()

    monkeypatch.setenv("EDP_ROLE", "worker")
    _run_main(hook, monkeypatch, capsys, _payload("worker-sid"), log_path)

    assert log_path.read_bytes() == before, "worker appended to the registry"
    assert sessions.latest_foreground_session(log_path)["session_id"] == \
        "real-foreground"


def test_is_foreground_predicate(hook):
    assert hook.is_foreground({}) is True
    assert hook.is_foreground({"EDP_ROLE": ""}) is True
    assert hook.is_foreground({"EDP_ROLE": "   "}) is True
    assert hook.is_foreground({"EDP_ROLE": "worker"}) is False


# ── (d) the reader returns the LAST entry, skipping a corrupt trailing line ──
def test_latest_returns_last_entry(log_path):
    log_path.parent.mkdir(parents=True)
    log_path.write_text(
        json.dumps({"session_id": "old", "cwd": "/a", "config_dir": None,
                    "started_at": "2026-07-09T10:00:00+00:00"}) + "\n" +
        json.dumps({"session_id": "new", "cwd": "/b",
                    "config_dir": r"C:\Users\me\.claude-personal",
                    "started_at": "2026-07-09T11:00:00+00:00"}) + "\n",
        encoding="utf-8")
    record = sessions.latest_foreground_session(log_path)
    assert record["session_id"] == "new"
    # config_dir is surfaced so the resume command can name the right launcher
    assert record["config_dir"] == r"C:\Users\me\.claude-personal"


def test_latest_skips_a_corrupt_trailing_line(log_path):
    """An interrupted write must not cost the caller a recoverable entry."""
    log_path.parent.mkdir(parents=True)
    log_path.write_text(
        json.dumps({"session_id": "good", "cwd": "/a", "config_dir": None,
                    "started_at": "2026-07-09T10:00:00+00:00"}) + "\n"
        + '{"session_id": "truncated", "cwd"\n',  # half-written line
        encoding="utf-8")
    assert sessions.latest_foreground_session(log_path)["session_id"] == "good"


def test_latest_skips_garbage_and_blank_lines(log_path):
    log_path.parent.mkdir(parents=True)
    log_path.write_text(
        json.dumps({"session_id": "good", "cwd": "/a", "config_dir": None,
                    "started_at": "2026-07-09T10:00:00+00:00"}) + "\n"
        + "\n"
        + "not json at all\n"
        + "[]\n"                              # valid JSON, wrong shape
        + '{"cwd": "/b"}\n'                   # dict without a session_id
        + '{"session_id": ""}\n'              # empty session_id
        + "   \n",
        encoding="utf-8")
    assert sessions.latest_foreground_session(log_path)["session_id"] == "good"


# ── (e) the reader returns None on a missing / empty / unusable file ─────────
def test_latest_returns_none_when_missing(log_path):
    assert not log_path.exists()
    assert sessions.latest_foreground_session(log_path) is None


@pytest.mark.parametrize("content", ["", "\n", "   \n\n", "garbage\n{oops\n"])
def test_latest_returns_none_when_nothing_is_usable(log_path, content):
    log_path.parent.mkdir(parents=True)
    log_path.write_text(content, encoding="utf-8")
    assert sessions.latest_foreground_session(log_path) is None


# ── round trip: what the hook writes is what the reader reads ───────────────
def test_hook_write_is_readable_by_the_reader(hook, monkeypatch, capsys,
                                              log_path):
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", r"C:\Users\me\.claude-personal")
    _run_main(hook, monkeypatch, capsys, _payload("round-trip"), log_path)
    record = sessions.latest_foreground_session(log_path)
    assert record["session_id"] == "round-trip"
    assert record["config_dir"] == r"C:\Users\me\.claude-personal"
    assert set(record) == _RECORD_KEYS


# ── anti-drift: the hook restates the path; it must equal the reader's ──────
def test_hook_and_reader_resolve_the_same_log_path(hook):
    assert hook.FOREGROUND_LOG == sessions.FOREGROUND_LOG
    assert hook.REPO_ROOT == sessions.REPO_ROOT == REPO
    assert sessions.FOREGROUND_LOG == REPO / ".sessions" / "foreground.jsonl"


# ── (f) settings.json: valid JSON, capture registered, compact NOT clobbered ─
def _session_start_entries():
    settings = json.loads(SETTINGS_PATH.read_text(encoding="utf-8"))
    return settings, settings["hooks"]["SessionStart"]


def test_settings_json_is_valid_and_preserves_the_compact_hook():
    """Regression guard: adding the capture hook must not clobber the
    pre-existing compact -> reground-on-compact.py entry."""
    settings, entries = _session_start_entries()
    compact = [e for e in entries if e["matcher"] == "compact"]
    assert len(compact) == 1, "the compact SessionStart entry was clobbered"
    commands = [h["command"] for h in compact[0]["hooks"]]
    assert any("reground-on-compact.py" in c for c in commands)
    # the other pre-existing wiring is untouched too
    assert settings["hooks"]["PreToolUse"]
    assert settings["permissions"]["allow"]


def test_settings_json_registers_the_capture_hook_for_non_compact_starts():
    _, entries = _session_start_entries()
    capture = [e for e in entries
               if any("capture-session.py" in h["command"] for h in e["hooks"])]
    assert len(capture) == 1, "capture-session.py is not registered exactly once"

    matcher = capture[0]["matcher"]
    for source in ("startup", "resume", "clear"):
        assert source in matcher, f"matcher does not cover {source!r}"
    assert "compact" not in matcher, "capture must not fire on compaction"

    command = capture[0]["hooks"][0]["command"]
    assert capture[0]["hooks"][0]["type"] == "command"
    # matches the invocation style of every other hook in this project
    assert "${CLAUDE_PROJECT_DIR}/.venv/Scripts/python.exe" in command
    assert "${CLAUDE_PROJECT_DIR}/.claude/hooks/capture-session.py" in command


def test_capture_hook_is_a_sibling_not_a_replacement():
    """The compact entry and the capture entry are DISTINCT SessionStart
    entries — neither hosts the other's script."""
    _, entries = _session_start_entries()
    assert len(entries) == 2
    by_matcher = {e["matcher"]: [h["command"] for h in e["hooks"]]
                  for e in entries}
    assert not any("capture-session.py" in c for c in by_matcher["compact"])
    assert all("reground-on-compact.py" not in c
               for m, cmds in by_matcher.items() if m != "compact"
               for c in cmds)
