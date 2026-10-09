"""s-bdc00a9ed2 (design-63db8a7d42 item L): doc tools shaped like file tools, plus the read-only docs mirror."""
from __future__ import annotations

import itertools
import os
import stat

os.environ.setdefault("EDP8_EMBEDDER", "none")

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from edp8 import doc_mirror  # noqa: E402
from edp8.board import Board  # noqa: E402
from edp8.bundles import ALL_TOOLS, set_client  # noqa: E402
from edp8.client import BoardClient  # noqa: E402
from edp8.doc_tools import _resolve_section, _headings  # noqa: E402
from edp8.service import create_app  # noqa: E402
from edp8.store import Store  # noqa: E402

ADMIN = {"X-Admin": "t"}
_N = itertools.count()  # doc_create replays an identical call (idempotency): every doc gets its own title
BODY = ("# Plan\n\n## 1. Purpose\nWhy.\n\n## 2. Install\n### 2.1 Windows\nrun it\n### 2.2 Linux\nrun it\n\n"
        "## 3. Testing\nrun run\n\n## Rollout plan\nslow\n")


def _call(http, who, name, **args):
    set_client(BoardClient(participant=who, client=http))
    t = ALL_TOOLS[name]
    r = t.handler(t.args_model(**args))
    if isinstance(r, dict) and r.get("ok") is False:
        raise RuntimeError(f"{r['error'].get('code')}: {r['error'].get('message')}")
    return r["value"] if isinstance(r, dict) and "value" in r else r


def _app(store):
    c = TestClient(create_app(Board(store), admin_token="t"))
    for pid, role, typ in [("arch", "architect", "agent"), ("eng", "engineer", "agent")]:
        assert c.post("/v1/participants", json={"type": typ, "role": role, "handle": pid, "id": pid},
                      headers=ADMIN).json()["ok"]
    return c


@pytest.fixture
def http():
    return _app(Store(":memory:"))


def _make(http, body=BODY, **extra):
    r = _call(http, "arch", "doc_create", doc_type="note", title=f"Plan {next(_N)}", scope="global", body=body,
              **extra)
    assert "id" in r, r
    return r["id"]


# ----------------------------------------------------------------------------- c-6030ac981d

def test_body_is_an_alias_of_body_md_on_create_and_update(http):
    d = _make(http)
    assert _call(http, "arch", "doc_read", id=d)["body_md"].startswith("# Plan")
    r = _call(http, "arch", "doc_update", id=d, body="# Plan\n\nnew\n")
    assert r["version"] == 2
    assert _call(http, "arch", "doc_read", id=d)["body_md"] == "# Plan\n\nnew\n"
    with pytest.raises(Exception):
        _call(http, "arch", "doc_create", doc_type="note", title="x", scope="global", body="a", body_md="b")
    with pytest.raises(Exception):
        _call(http, "arch", "doc_create", doc_type="note", title="x", scope="global")


def test_doc_edit_native_shape_defaults_to_the_version_last_served(http):
    d = _make(http)
    _call(http, "arch", "doc_read", id=d)
    r = _call(http, "arch", "doc_edit", id=d, old_string="Why.", new_string="Because.")
    assert r["version"] == 2
    # the writer's own write is the version it holds: a second edit needs no re-read
    r = _call(http, "arch", "doc_edit", id=d, old_string="Because.", new_string="Since.")
    assert r["version"] == 3
    assert "Since." in _call(http, "arch", "doc_read", id=d, section="## 1. Purpose")["body_md"]


def test_doc_edit_without_a_read_uses_the_latest_and_a_stale_reader_conflicts(http):
    d = _make(http)
    assert _call(http, "eng", "doc_edit", id=d, old_string="Why.", new_string="Now.")["version"] == 2  # none served
    _call(http, "arch", "doc_read", id=d)                                         # arch holds v2
    _call(http, "eng", "doc_edit", id=d, old_string="Now.", new_string="Then.")  # v3
    with pytest.raises(Exception, match="version"):
        _call(http, "arch", "doc_edit", id=d, old_string="Then.", new_string="x")


def test_doc_edit_list_replace_all_and_old_aliases(http):
    d = _make(http)
    r = _call(http, "arch", "doc_edit", id=d, edits=[{"old_string": "run it", "new_string": "go", "replace_all": True},
                                                    {"old_text": "slow", "new_text": "fast"}])
    assert r["version"] == 2
    body = _call(http, "arch", "doc_read", id=d, limit=32768)["body_md"]
    assert body.count("go") == 2 and "fast" in body and "run it" not in body
    with pytest.raises(Exception, match="exactly once"):
        _call(http, "arch", "doc_edit", id=d, old_string="run", new_string="x")  # ambiguous without replace_all
    with pytest.raises(Exception):
        _call(http, "arch", "doc_edit", id=d)                                    # nothing to edit


def test_doc_edit_explicit_expected_version_still_pins(http):
    d = _make(http)
    with pytest.raises(Exception, match="version"):
        _call(http, "arch", "doc_edit", id=d, expected_version=7, old_string="Why.", new_string="x")


def _sec(section):
    lines = BODY.splitlines(keepends=True)
    return lines[_resolve_section(lines, _headings(lines), section)].strip()


@pytest.mark.parametrize("ask,want", [
    ("2", "## 2. Install"), ("3", "## 3. Testing"), ("2.1", "### 2.1 Windows"), ("§2.2", "### 2.2 Linux"),
    ("## 3. Testing", "## 3. Testing"), ("testing", "## 3. Testing"), ("Rollout", "## Rollout plan"),
    ("windows", "### 2.1 Windows"), ("Rollout plan", "## Rollout plan"),
])
def test_section_takes_a_number_or_a_near_heading(ask, want):
    assert _sec(ask) == want


def test_section_positional_numbers_when_headings_carry_none():
    body = "# T\n\n## Alpha\na\n### One\n1\n### Two\n2\n\n## Beta\nb\n"
    lines = body.splitlines(keepends=True)
    heads = _headings(lines)
    assert lines[_resolve_section(lines, heads, "2")].strip() == "## Beta"
    assert lines[_resolve_section(lines, heads, "1.2")].strip() == "### Two"


def test_ambiguous_section_answers_with_candidates():
    from edp8.board import BoardError
    lines = BODY.splitlines(keepends=True)
    with pytest.raises(BoardError) as e:
        _resolve_section(lines, _headings(lines), "run")  # no heading holds "run"
    assert "section_match" in str(e.value.code)
    with pytest.raises(BoardError) as e:
        _resolve_section(lines, _headings(lines), "in")   # a loose match of several headings
    assert "candidates" in str(e.value) and "2.1 Windows" in str(e.value)


# ----------------------------------------------------------------------------- c-699c055cd5

@pytest.fixture
def mirrored(tmp_path):
    store = Store(str(tmp_path / "edp8.db"))
    store.mirror_root = tmp_path / "home" / "docs"
    return _app(store), store.mirror_root, store


def _file(root, scope, doc_id):
    return root / scope / f"{doc_id}.md"


def test_every_doc_write_updates_the_mirror_and_the_file_is_read_only(mirrored):
    http, root, _ = mirrored
    d = _make(http)
    f = _file(root, "global", d)
    assert f.read_text(encoding="utf-8").endswith(BODY) and f"id: {d}" in f.read_text(encoding="utf-8")
    assert not os.access(f, os.W_OK) and not f.stat().st_mode & stat.S_IWRITE
    with pytest.raises(PermissionError):
        f.write_text("native edit", encoding="utf-8")  # a native Edit on a mirror file fails
    _call(http, "arch", "doc_edit", id=d, old_string="Why.", new_string="Because.")
    assert "Because." in f.read_text(encoding="utf-8") and "version: 2" in f.read_text(encoding="utf-8")
    _call(http, "arch", "doc_update", id=d, body="# Plan\n\nrewritten\n")
    assert f.read_text(encoding="utf-8").endswith("rewritten\n") and "version: 3" in f.read_text(encoding="utf-8")
    assert not list(root.glob("*/*.tmp"))


def test_a_scope_with_a_colon_is_a_safe_folder_name(mirrored):
    http, root, _ = mirrored
    d = _call(http, "arch", "doc_create", doc_type="note", title=f"Dom {next(_N)}", scope="domain:ops", body="# D\n")["id"]
    assert _file(root, "domain-ops", d).is_file()


def test_a_failed_database_write_changes_neither_copy(mirrored, monkeypatch):
    http, root, store = mirrored
    d = _make(http)
    f = _file(root, "global", d)
    before = f.read_text(encoding="utf-8")

    def boom(*a, **k):
        raise RuntimeError("fts down")
    monkeypatch.setattr(store, "_fts_put_locked", boom)
    with pytest.raises(Exception):
        store._conn.execute("SELECT 1")
        doc = store.get("doc", d)
        doc.body_md, doc.version = "# Plan\n\nLOST\n", doc.version + 1
        store.put("doc", doc)
    assert f.read_text(encoding="utf-8") == before
    assert store.get("doc", d).body_md == BODY and store.get("doc", d).version == 1


def test_a_failed_mirror_stage_rolls_the_database_back(mirrored, monkeypatch):
    http, root, store = mirrored
    d = _make(http)
    monkeypatch.setattr(doc_mirror, "stage", lambda *a: (_ for _ in ()).throw(OSError("disk full")))
    with pytest.raises(OSError):
        doc = store.get("doc", d)
        doc.body_md, doc.version = "# Plan\n\nLOST\n", doc.version + 1
        store.put("doc", doc)
    assert store.get("doc", d).body_md == BODY
    assert "LOST" not in _file(root, "global", d).read_text(encoding="utf-8")


def test_backfill_writes_existing_docs_once_and_repairs_a_changed_file(tmp_path):
    store = Store(str(tmp_path / "edp8.db"))
    http = _app(store)  # no mirror yet: the docs exist only in the database
    a, b = _make(http), _make(http, body="# Other\n")
    root = tmp_path / "home" / "docs"
    assert doc_mirror.backfill(store, root) == {"written": 2, "same": 0, "failed": 0}
    assert doc_mirror.backfill(store, root) == {"written": 0, "same": 2, "failed": 0}
    f = _file(root, "global", a)
    os.chmod(f, stat.S_IWRITE | stat.S_IREAD)
    f.write_text("tampered", encoding="utf-8")
    assert doc_mirror.backfill(store, root)["written"] == 1
    assert f.read_text(encoding="utf-8").endswith(BODY) and not os.access(f, os.W_OK)
    assert _file(root, "global", b).is_file()


def test_mirror_path_never_leaves_the_root(tmp_path):
    class D:
        id, scope = "note-x", "../../etc"
    p = doc_mirror.mirror_path(tmp_path / "docs", D)
    assert (tmp_path / "docs").resolve() in p.resolve().parents


# ----------------------------------------------------------------------------- c-61ca90bf31

def test_doc_read_no_longer_nudges_a_rewrite_and_output_keeps_non_ascii(http):
    from edp8.mcp_server import _as_content
    from edp8.schemas import LEGACY_WARNING
    assert "rewrit" not in LEGACY_WARNING.replace("do not rewrite", "")
    d = _make(http, body="# Café\n\nnaïve – ✓\n")
    out = _as_content({"ok": True, "value": _call(http, "arch", "doc_read", id=d)})
    assert "naïve – ✓" in out and "\\u" not in out


def test_the_skill_says_small_prose_large_summary_first_edit_dont_rewrite():
    from pathlib import Path
    text = Path(__file__).resolve().parents[1].joinpath(".claude/skills/doc-write/SKILL.md").read_text(encoding="utf-8")
    low = text.lower()
    assert "small (one point) = plain prose" in low or "small (one point) = plain prose." in low.replace("**", "")
    assert "large (several parts) = summary first" in low.replace("**", "")
    assert "edit, don't rewrite" in low


def test_mirror_is_off_when_the_agent_home_is_a_source_checkout(tmp_path, monkeypatch):
    """A dev board whose agent home is the repo's v8/ (pyproject.toml present) never writes board docs into the
    tracked docs/ folder; an installed agent home (no pyproject) gets the mirror."""
    from types import SimpleNamespace
    from edp8 import service, settings
    data = tmp_path / "data"
    home = data / "agent-home"
    home.mkdir(parents=True)
    monkeypatch.delenv("EDP8_DOC_MIRROR", raising=False)
    monkeypatch.setattr(settings, "data_dir", lambda: data)
    monkeypatch.setattr(settings, "agent_home", lambda: home)
    store = SimpleNamespace(path=str(data / "board.db"))
    assert service._doc_mirror_wanted(store) is True
    (home / "pyproject.toml").write_text("[project]\n", encoding="utf-8")
    assert service._doc_mirror_wanted(store) is False


# ----------------------------------------------------------------------------- Astra review fixes (report-8115d2915f)

def test_f1_an_open_reader_never_leaves_a_stale_or_writable_mirror(mirrored, monkeypatch):
    """F1: a reader holding the mirror file open (Windows refuses the replace) must not leave a writable file; the
    doc is queued and the next write catches it up."""
    http, root, store = mirrored
    d = _make(http)
    f = _file(root, "global", d)
    real = os.replace
    blocked = {"on": True}

    def replace(src, dst):
        if blocked["on"] and str(dst) == str(f):
            raise PermissionError(32, "The process cannot access the file because it is being used by another process")
        return real(src, dst)
    monkeypatch.setattr(os, "replace", replace)
    monkeypatch.setattr(doc_mirror.time, "sleep", lambda s: None)
    assert _call(http, "arch", "doc_edit", id=d, old_string="Why.", new_string="Because.")["version"] == 2
    assert "Why." in f.read_text(encoding="utf-8") and not os.access(f, os.W_OK)  # stale, but still read-only
    assert d in store.mirror_pending
    blocked["on"] = False                                                          # the reader let go
    other = _make(http, body="# Other\n")                                          # the next commit repairs the queue
    assert "Because." in f.read_text(encoding="utf-8") and not os.access(f, os.W_OK)
    assert d not in store.mirror_pending and _file(root, "global", other).is_file()


@pytest.mark.skipif(os.name != "nt", reason="a reader blocks the replace on Windows")
def test_f1_a_real_open_reader_on_windows(mirrored, monkeypatch):
    http, root, store = mirrored
    d = _make(http)
    f = _file(root, "global", d)
    monkeypatch.setattr(doc_mirror.time, "sleep", lambda s: None)
    with open(f, "rb"):
        _call(http, "arch", "doc_edit", id=d, old_string="Why.", new_string="Because.")
        assert not os.access(f, os.W_OK) and d in store.mirror_pending
    _make(http, body="# Other\n")
    assert "Because." in f.read_text(encoding="utf-8") and d not in store.mirror_pending


def test_f1_backfill_counts_a_failed_publish_as_failed(tmp_path, monkeypatch):
    store = Store(str(tmp_path / "edp8.db"))
    http = _app(store)
    d = _make(http)
    root = tmp_path / "home" / "docs"
    monkeypatch.setattr(doc_mirror, "publish", lambda *a, **k: False)
    assert doc_mirror.backfill(store, root) == {"written": 0, "same": 0, "failed": 1}
    assert d in store.mirror_pending


def test_f2_a_rolled_back_write_leaves_no_staged_body(mirrored, monkeypatch):
    http, root, store = mirrored
    d = _make(http)
    monkeypatch.setattr(store, "_fts_put_locked", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("fts down")))
    with pytest.raises(RuntimeError):
        doc = store.get("doc", d)
        doc.body_md, doc.version = "# Plan\n\nUNCOMMITTED_MARKER\n", doc.version + 1
        store.put("doc", doc)
    for p in root.rglob("*"):
        if p.is_file():
            assert "UNCOMMITTED_MARKER" not in p.read_text(encoding="utf-8"), p
    assert not list(root.rglob("*.md.tmp"))
    assert all(p.suffix != ".md" for p in (root / ".staging").glob("*"))  # staging is never a searchable .md
    assert _file(root, "global", d).read_text(encoding="utf-8").endswith(BODY)


def test_f2_a_committed_write_leaves_the_staging_folder_empty(mirrored):
    http, root, _ = mirrored
    _make(http)
    assert not list((root / ".staging").glob("*"))


@pytest.mark.parametrize("ask", ["0", "-1", "1.0", "1.-2", "2.0", "0.1", "§0"])
def test_f3_zero_and_negative_section_numbers_are_refused_with_a_hint(ask):
    from edp8.board import BoardError
    lines = "# T\n\n## Alpha\na\n\n## Beta\nb\n".splitlines(keepends=True)
    with pytest.raises(BoardError) as e:
        _resolve_section(lines, _headings(lines), ask)
    assert e.value.code == "section_match" and "count from 1" in (e.value.hint or "")


def test_f3_a_zero_section_is_a_refusal_over_http_not_a_500(http):
    d = _make(http)
    for ask in ("0", "1.0", "-1"):
        r = _call_raw(http, "arch", "doc_read", id=d, section=ask)
        assert r["ok"] is False and r["error"]["code"] == "section_match", r
    raw = http.get(f"/v1/docs/{d}", params={"section": "0"}, headers={"X-Participant": "arch"})
    assert raw.status_code < 500


def test_f3_a_heading_that_is_itself_numbered_zero_still_resolves():
    lines = "# T\n\n## 0. Preface\np\n\n## 1. Body\nb\n".splitlines(keepends=True)
    assert lines[_resolve_section(lines, _headings(lines), "0")].strip() == "## 0. Preface"


def _call_raw(http, who, name, **args):
    set_client(BoardClient(participant=who, client=http))
    t = ALL_TOOLS[name]
    return t.handler(t.args_model(**args))


def _transcript(path, rows):
    import json
    path.write_text("\n".join(json.dumps(r) for r in rows) + "\n", encoding="utf-8")


def _use(i, name, ts, **inp):
    return {"timestamp": ts, "message": {"content": [{"type": "tool_use", "id": i, "name": "mcp__edp8__" + name,
                                                        "input": inp}]}}


def _res(i, ts, text, error=False):
    return {"timestamp": ts, "message": {"content": [{"type": "tool_result", "tool_use_id": i, "is_error": error,
                                                        "content": [{"type": "text", "text": text}]}]}}


def _baseline():
    import importlib.util
    from pathlib import Path
    spec = importlib.util.spec_from_file_location(
        "doc_call_baseline", Path(__file__).resolve().parents[1] / "scripts" / "doc_call_baseline.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_f4_a_call_crossing_midnight_is_counted_once_in_the_window_it_started(tmp_path):
    _transcript(tmp_path / "s.jsonl", [
        _use("a", "doc_edit", "2026-10-08T23:59:59Z", id="x", old_string="a", new_string="b"),
        _res("a", "2026-10-09T00:00:01Z", '{"ok": false, "error": {"message": "edit_match"}}'),
    ])
    mod = _baseline()
    before = mod.scan(tmp_path, None, "2026-10-09")
    after = mod.scan(tmp_path, "2026-10-09", None)
    assert (before["doc_calls"], before["doc_call_errors"]) == (1, 1)
    assert (after["doc_calls"], after["doc_call_errors"]) == (0, 0)


def test_f4_only_successful_writes_count_as_changes(tmp_path):
    _transcript(tmp_path / "s.jsonl", [
        _use("a", "doc_edit", "2026-10-08T10:00:00Z", id="x", old_string="a" * 10, new_string="b"),
        _res("a", "2026-10-08T10:00:01Z", '{"ok": false, "error": {"message": "validation error"}}'),
        _use("b", "doc_update", "2026-10-08T10:01:00Z", id="x", body_md="c" * 100),
        _res("b", "2026-10-08T10:01:01Z", '{"ok": true, "value": {}}'),
        _use("c", "doc_create", "2026-10-08T10:02:00Z", title="t"),
    ])
    out = _baseline().scan(tmp_path, None, None)
    assert out["doc_changes"] == 1 and out["attempted_writes"] == 3 and out["calls_without_result"] == 1
    assert out["median_bytes_per_change"] > 100 and out["error_classes"] == {"argument_shape": 1}


def test_q1_an_edit_with_no_doc_read_says_it_applied_to_the_latest(http):
    d = _make(http)
    r = _call(http, "eng", "doc_edit", id=d, old_string="Why.", new_string="Now.")
    assert "version_pin" in r and r["version"] == 2
    http.post("/v1/docs/reads/reset", headers={"X-Participant": "arch"})  # arch holds nothing (resume_self)
    raw = _call_raw(http, "arch", "doc_edit", id=d, old_string="Now.", new_string="Then.")
    assert "expected_version" in raw["hint"] and "front-matter" in raw["hint"]
    _call(http, "arch", "doc_read", id=d)
    served = _call_raw(http, "arch", "doc_edit", id=d, old_string="Then.", new_string="Again.")
    assert "version_pin" not in served["value"] and "front-matter" not in served["hint"]
    pinned = _call_raw(http, "eng", "doc_edit", id=d, expected_version=4, old_string="Again.", new_string="Z.")
    assert "version_pin" not in pinned["value"]


def test_q1_the_skill_says_a_native_read_pins_no_version():
    from pathlib import Path
    text = Path(__file__).resolve().parents[1].joinpath(".claude/skills/doc-write/SKILL.md").read_text(encoding="utf-8")
    assert "native Read pins no version" in text and "front-matter `version:`" in text
