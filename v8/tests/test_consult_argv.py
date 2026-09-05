"""consult bridge — pure argv/parse contracts plus the S0c profile / boundary /
evidence contract (criteria c-9f87c3d102, c-198d217e38, c-7001dd4631).

The subprocess is stubbed at `consult._run_codex` (the single launch point); a fake
emulates codex by writing the `-o` last-message file parsed out of the argv, so the
tests assert the exact argv/config a reviewer re-runs, never spawning codex."""

from __future__ import annotations

import json
import os
import struct
import subprocess
import zlib
from pathlib import Path

import pytest

from edp8 import consult as consult_mod
from edp8.consult import (
    _build_argv,
    _profile_config_args,
    _PROFILES,
    _real_escapes,
    _snapshot_mtimes,
    check_write_dir_boundary,
    discover_mcp_servers,
    fence_remediate,
    git_status_map,
    image_evidence,
    mcp_disable_args,
    mcp_disabled_names,
    parse_provider_model,
    parse_thread_id,
    parse_verdict,
    profile_skill_intent,
    resolve_profile,
)


def _norm(p) -> str:
    """Normcased realpath — the key shape `_writes_outside` emits and `fence_remediate`
    expects for an escaped path."""
    return os.path.normcase(os.path.realpath(str(p)))


def _git_init(root: Path, tracked_name: str = "tracked.txt", body: str = "original\n") -> Path:
    """Init a git repo at `root` with one committed tracked file; return its path."""
    root.mkdir(parents=True, exist_ok=True)
    env_id = ["-c", "user.email=t@e.st", "-c", "user.name=test"]
    subprocess.run(["git", "-C", str(root), "init", "-q"], check=True,
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    tracked = root / tracked_name
    tracked.write_text(body, encoding="utf-8")
    subprocess.run(["git", "-C", str(root), "add", "-A"], check=True,
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    subprocess.run(["git", "-C", str(root), *env_id, "commit", "-q", "-m", "init"],
                   check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    return tracked

#: A realistic `codex mcp list --json` result: the 5 config.toml servers plus the
#: plugin-injected cua_repl (stdio, no config.toml table) that the old static
#: denylist missed — the c-9f87c3d102 regression case, and the default the consult()
#: fixtures inject so no test spawns the real `codex mcp list`.
_FAKE_MCP = [
    {"name": "chrome-devtools", "transport": "stdio"},
    {"name": "cua_repl", "transport": "stdio"},
    {"name": "edp-claude", "transport": "stdio"},
    {"name": "node_repl", "transport": "stdio"},
    {"name": "playwright", "transport": "stdio"},
    {"name": "unreal-mcp", "transport": "streamable_http"},
]


# ---------------------------------------------------------------- pure argv

def _base(**kw):
    kw.setdefault("prompt", "hello")
    kw.setdefault("workdir", "C:/w")
    kw.setdefault("last_message_file", "C:/w/last.txt")
    kw.setdefault("model", "gpt-6-astra")
    kw.setdefault("effort", "medium")
    return _build_argv("codex", **kw)


def test_fresh_turn_prompt_last_behind_double_dash():
    argv = _base()
    assert argv[:2] == ["codex", "exec"]
    assert argv[-2:] == ["--", "hello"]
    assert "resume" not in argv and "-i" not in argv


def test_fresh_turn_images_are_variadic_and_terminated():
    argv = _base(images=["a.png", "b.png"])
    i = argv.index("-i")
    assert argv[i:i + 3] == ["-i", "a.png", "b.png"]
    assert argv[i + 3:] == ["--", "hello"]        # `--` terminates the variadic -i


def test_resume_turn_shape():
    argv = _base(resume_thread="0199-thread", images=["shot.png"])
    r = argv.index("resume")
    assert argv.index("-m") < r and argv.index("-c") < r
    assert argv[r:] == ["resume", "-i", "shot.png", "--", "0199-thread", "hello"]


def test_resume_without_images():
    argv = _base(resume_thread="t1")
    assert argv[-4:] == ["resume", "--", "t1", "hello"]


def test_config_args_are_globals_before_subcommand():
    cfg = ["-c", "approval_policy=never", "-c", "features.image_generation=true"]
    argv = _base(config_args=cfg, resume_thread="t1")
    r = argv.index("resume")
    # every config arg sits before the resume subcommand
    assert all(argv.index(tok) < r for tok in ("approval_policy=never", "features.image_generation=true"))


def test_parse_thread_id_from_stream():
    raw = "\n".join([
        "Reading additional input from stdin...",
        json.dumps({"type": "thread.started", "thread_id": "01a05efd-dea4-7ed3-b289-444bda9e744d"}),
        json.dumps({"type": "turn.started"}),
        "{not json",
    ])
    assert parse_thread_id(raw) == "01a05efd-dea4-7ed3-b289-444bda9e744d"


def test_parse_thread_id_absent():
    assert parse_thread_id("no events here\n{\"type\":\"turn.completed\"}") is None


def test_parse_provider_model_from_stream():
    raw = "\n".join([
        json.dumps({"type": "thread.started", "thread_id": "t"}),
        json.dumps({"type": "turn.started", "turn": {"model": "gpt-6-astra-2026-09-01"}}),
    ])
    assert parse_provider_model(raw) == "gpt-6-astra-2026-09-01"
    assert parse_provider_model("no model here") is None


# ------------------------------------------------- profiles (c-9f87c3d102)

def test_purpose_maps_to_profile():
    assert resolve_profile("adversary", None) == ("design", None)
    assert resolve_profile("second_opinion", None) == ("design", None)
    assert resolve_profile("creative", None) == ("concept", None)
    assert resolve_profile("visual", None) == ("verify", None)
    assert resolve_profile("build", None) == ("blender", None)


def test_explicit_profile_overrides_purpose():
    assert resolve_profile("build", "verify") == ("verify", None)


def test_unknown_profile_rejected():
    name, err = resolve_profile("build", "nope")
    assert name is None and "unknown profile" in err


def test_sandbox_and_effort_per_profile():
    assert (_PROFILES["design"].sandbox, _PROFILES["design"].effort) == ("read-only", "medium")
    assert (_PROFILES["verify"].sandbox, _PROFILES["verify"].effort) == ("read-only", "high")
    assert (_PROFILES["direct"].sandbox, _PROFILES["direct"].effort) == ("read-only", "medium")
    assert _PROFILES["concept"].sandbox == "workspace-write" and _PROFILES["concept"].writes
    assert _PROFILES["blender"].sandbox == "workspace-write" and _PROFILES["blender"].writes


def _cfg(profile: str) -> str:
    return " ".join(_profile_config_args(_PROFILES[profile]))


def test_approval_never_every_profile_no_static_mcp_in_pure_args():
    # the pure profile args carry approval_policy but NOT a static MCP list — the
    # server disable set is discovered at call time (c-9f87c3d102 regression fix).
    for p in _PROFILES:
        c = _cfg(p)
        assert "approval_policy=never" in c
        assert "mcp_servers." not in c, p


# ------------------------------------- MCP discover-and-disable (c-9f87c3d102)

def test_mcp_disable_args_disables_every_discovered_server():
    args = mcp_disable_args(_FAKE_MCP)
    joined = " ".join(args)
    for srv in ("chrome-devtools", "cua_repl", "edp-claude", "node_repl",
                "playwright", "unreal-mcp"):
        assert f"mcp_servers.{srv}.enabled=false" in joined, srv


def test_mcp_disable_stdio_gets_stub_command_url_does_not():
    args = " ".join(mcp_disable_args(_FAKE_MCP))
    # a plugin-injected stdio server (cua_repl) needs a stub command so the -c merge
    # is a valid disabled table; a url/http server (unreal-mcp) must NOT get one.
    assert 'mcp_servers.cua_repl.command="edp8-disabled"' in args
    assert "mcp_servers.unreal-mcp.command" not in args


def test_mcp_disable_unknown_server_yields_disable_flag():
    # architect m-683619d164 (4): a discovery output with a server the code never
    # heard of still yields the disable flag — discover-and-disable, not a denylist.
    args = " ".join(mcp_disable_args([{"name": "brand-new-surface", "transport": "stdio"}]))
    assert "mcp_servers.brand-new-surface.enabled=false" in args
    assert 'mcp_servers.brand-new-surface.command="edp8-disabled"' in args


def test_mcp_floor_added_when_discovery_misses_unreal():
    # discovery returns nothing → unreal-mcp is still disabled as a hard floor.
    args = " ".join(mcp_disable_args([]))
    assert "mcp_servers.unreal-mcp.enabled=false" in args
    assert mcp_disabled_names([]) == ["unreal-mcp"]


def test_mcp_floor_not_duplicated_when_discovered():
    names = mcp_disabled_names(_FAKE_MCP)
    assert names.count("unreal-mcp") == 1
    assert names == sorted({s["name"] for s in _FAKE_MCP})


def test_discover_parses_json_and_transport(monkeypatch):
    payload = json.dumps([
        {"name": "cua_repl", "transport": {"type": "stdio", "command": "node"}},
        {"name": "unreal-mcp", "transport": {"type": "streamable_http", "url": "http://x"}},
    ])

    def fake_run(argv, **kw):
        assert argv[:3] == ["codex", "mcp", "list"] and "--json" in argv
        return subprocess.CompletedProcess(argv, 0, stdout=payload, stderr="")

    monkeypatch.setattr(consult_mod.subprocess, "run", fake_run)
    servers, err = discover_mcp_servers("codex")
    assert err is None
    assert servers == [{"name": "cua_repl", "transport": "stdio"},
                       {"name": "unreal-mcp", "transport": "streamable_http"}]


def test_discover_nonzero_exit_is_fail_closed(monkeypatch):
    def fake_run(argv, **kw):
        return subprocess.CompletedProcess(argv, 1, stdout="", stderr="boom")

    monkeypatch.setattr(consult_mod.subprocess, "run", fake_run)
    servers, err = discover_mcp_servers("codex")
    assert servers == [] and err and "exited 1" in err


def test_discover_unparseable_is_fail_closed(monkeypatch):
    def fake_run(argv, **kw):
        return subprocess.CompletedProcess(argv, 0, stdout="not json", stderr="")

    monkeypatch.setattr(consult_mod.subprocess, "run", fake_run)
    servers, err = discover_mcp_servers("codex")
    assert servers == [] and err and "not JSON" in err


def test_image_generation_only_in_concept():
    assert "features.image_generation=true" in _cfg("concept")
    for p in ("design", "blender", "verify", "direct"):
        assert "features.image_generation=false" in _cfg(p), p


def test_browser_use_only_in_design_computer_use_never():
    assert "features.browser_use=true" in _cfg("design")
    for p in ("concept", "blender", "verify", "direct"):
        assert "features.browser_use=false" in _cfg(p), p
    for p in _PROFILES:
        assert "features.computer_use=false" in _cfg(p), p


def test_skills_config_never_reaches_exec_argv():
    # codex 0.153.4 `exec` rejects -c skills.config; it must not appear on argv.
    for p in _PROFILES:
        assert "skills.config" not in _cfg(p), p


def test_asset_skill_intent_recorded_only_in_concept_and_blender():
    for p in ("concept", "blender"):
        intent = profile_skill_intent(_PROFILES[p])
        assert intent["photoreal-asset-factory"] is True, p
        assert intent["terrain-geology-assets"] is True, p
    for p in ("design", "verify", "direct"):
        intent = profile_skill_intent(_PROFILES[p])
        assert intent["photoreal-asset-factory"] is False, p
        assert intent["terrain-geology-assets"] is False, p
    # every managed skill is off by default in a read-only profile
    assert not any(profile_skill_intent(_PROFILES["direct"]).values())


# --------------------------------------------- test doubles for consult()

def _fake_codex(*, answer: str | None, thread: str | None = "tid-1",
                provider_model: str | None = None, exit_code: int = 0,
                timed_out: bool = False, writes_file: str | None = None):
    """Return a stand-in for consult._run_codex that emulates codex: writes the
    `-o` last-message file (unless answer is None → fail-closed path) and streams a
    thread.started event. `writes_file` simulates a rogue write to that path."""
    def fake(argv, timeout_s):
        lines = []
        if thread:
            lines.append(json.dumps({"type": "thread.started", "thread_id": thread}))
        if provider_model:
            lines.append(json.dumps({"type": "turn.started", "model": provider_model}))
        if writes_file:
            Path(writes_file).parent.mkdir(parents=True, exist_ok=True)
            Path(writes_file).write_text("rogue", encoding="utf-8")
            # emit a shell event naming the write, so the fence can ATTRIBUTE it to
            # this run's codex (the log is the primary attribution signal).
            lines.append(json.dumps({"type": "item.completed", "item": {
                "type": "command_execution",
                "command": f"Set-Content {Path(writes_file).name} rogue"}}))
        if answer is not None:
            o = argv[argv.index("-o") + 1]
            Path(o).write_text(answer, encoding="utf-8")
        return "\n".join(lines) + "\n", (None if timed_out else exit_code), timed_out
    return fake


@pytest.fixture
def _logs(tmp_path, monkeypatch):
    monkeypatch.setenv(consult_mod._LOG_DIR_ENV, str(tmp_path / "logs"))
    monkeypatch.setattr(consult_mod, "_resolve_bin", lambda: "codex")
    # UE root at an unrelated absent path — never an ancestor/descendant of tmp_path,
    # so a tmp_path write_dir is neither inside nor a parent of it.
    monkeypatch.setenv(consult_mod._UE_ROOT_ENV, r"C:\Projects\__edp8_test_ue_absent__")
    # stub MCP discovery so consult() never spawns the real `codex mcp list`; the
    # fake set includes the plugin-injected cua_repl the old denylist missed.
    monkeypatch.setattr(consult_mod, "discover_mcp_servers",
                        lambda codex, timeout_s=30: (list(_FAKE_MCP), None))
    return tmp_path


def _load_manifest(resp) -> dict:
    return json.loads(Path(resp["value"]["manifest"]).read_text(encoding="utf-8"))


def test_consult_argv_carries_profile_config_and_sandbox(_logs, monkeypatch):
    seen = {}

    def spy(argv, timeout_s):
        seen["argv"] = argv
        Path(argv[argv.index("-o") + 1]).write_text("ok", encoding="utf-8")
        return json.dumps({"type": "thread.started", "thread_id": "t"}) + "\n", 0, False

    monkeypatch.setattr(consult_mod, "_run_codex", spy)
    resp = consult_mod.consult("second_opinion", "q")   # → design profile
    assert resp["ok"], resp
    argv = seen["argv"]
    assert "-s" in argv and argv[argv.index("-s") + 1] == "read-only"
    joined = " ".join(argv)
    assert "approval_policy=never" in joined
    assert "mcp_servers.unreal-mcp.enabled=false" in joined
    # the discovered plugin-injected server is contained in the read-only profile too
    assert 'mcp_servers.cua_repl.command="edp8-disabled"' in joined
    assert "mcp_servers.cua_repl.enabled=false" in joined
    assert resp["value"]["profile"] == "design"


def test_manifest_records_effective_profile_and_config(_logs, monkeypatch):
    monkeypatch.setattr(consult_mod, "_run_codex", _fake_codex(answer="hi"))
    resp = consult_mod.consult("visual", "check")   # → verify
    assert resp["ok"], resp
    man = _load_manifest(resp)
    assert man["profile"] == "verify"
    assert man["sandbox"] == "read-only" and man["approval_policy"] == "never"
    assert man["features"]["image_generation"] is False
    assert man["skills"]["photoreal-asset-factory"] is False
    assert man["config_args"] and man["image_gen_retried"] is False
    # discovered == disabled (cua_repl included); both recorded, denylist gone
    assert "cua_repl" in man["mcp_discovered"]
    assert man["mcp_disabled"] == man["mcp_discovered"]
    assert man["mcp_servers_disabled"] == man["mcp_disabled"]


def test_consult_fails_closed_when_mcp_discovery_fails(_logs, monkeypatch):
    monkeypatch.setattr(consult_mod, "discover_mcp_servers",
                        lambda codex, timeout_s=30: ([], "`codex mcp list --json` exited 1: boom"))

    def boom(argv, timeout_s):
        raise AssertionError("codex must not run when MCP discovery fails")

    monkeypatch.setattr(consult_mod, "_run_codex", boom)
    resp = consult_mod.consult("second_opinion", "q")
    assert resp["ok"] is False and resp["error"]["code"] == "mcp_discovery"


def test_requested_vs_provider_model_recorded(_logs, monkeypatch):
    monkeypatch.setattr(consult_mod, "_run_codex",
                        _fake_codex(answer="hi", provider_model="gpt-6-astra-snap"))
    resp = consult_mod.consult("second_opinion", "q", model="gpt-6-astra")
    assert resp["value"]["model"] == "gpt-6-astra"
    assert resp["value"]["provider_model"] == "gpt-6-astra-snap"


def test_single_invocation_no_retry(_logs, monkeypatch):
    calls = {"n": 0}

    def once(argv, timeout_s):
        calls["n"] += 1
        Path(argv[argv.index("-o") + 1]).write_text("hi", encoding="utf-8")
        return "\n", 0, False

    monkeypatch.setattr(consult_mod, "_run_codex", once)
    consult_mod.consult("creative", "gen", write_dir=str(_logs))
    assert calls["n"] == 1   # image_gen / anything is never auto-retried


# ------------------------------------------------- fail-closed (c-7001dd4631)

def test_no_final_answer_fails_closed(_logs, monkeypatch):
    monkeypatch.setattr(consult_mod, "_run_codex", _fake_codex(answer=None))
    resp = consult_mod.consult("second_opinion", "q")
    assert resp["ok"] is False and resp["error"]["code"] == "no_answer"


def test_timeout_preserves_thread_id(_logs, monkeypatch):
    monkeypatch.setattr(consult_mod, "_run_codex",
                        _fake_codex(answer=None, thread="tid-keep", timed_out=True))
    resp = consult_mod.consult("second_opinion", "q")
    assert resp["ok"] is False and resp["error"]["code"] == "timeout"
    assert resp["value"]["thread_id"] == "tid-keep"


# --------------------------------------------------- images (c-7001dd4631)

def _valid_png(path: Path) -> Path:
    def chunk(typ, data):
        c = typ + data
        return struct.pack(">I", len(data)) + c + struct.pack(">I", zlib.crc32(c) & 0xFFFFFFFF)
    ihdr = struct.pack(">IIBBBBB", 1, 1, 8, 2, 0, 0, 0)
    idat = zlib.compress(b"\x00\xff\xff\xff")
    path.write_bytes(b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", ihdr)
                     + chunk(b"IDAT", idat) + chunk(b"IEND", b""))
    return path


def test_undecodable_image_fails_before_run(_logs, monkeypatch):
    bad = _logs / "bad.png"
    bad.write_bytes(b"\x89PNG\r\n\x1a\nnot really a png")

    def boom(argv, timeout_s):
        raise AssertionError("codex must not run when an image is undecodable")

    monkeypatch.setattr(consult_mod, "_run_codex", boom)
    resp = consult_mod.consult("visual", "look", images=[str(bad)])
    assert resp["ok"] is False and resp["error"]["code"] == "image"


def test_valid_image_hashed_in_manifest(_logs, monkeypatch):
    img = _valid_png(_logs / "shot.png")
    monkeypatch.setattr(consult_mod, "_run_codex", _fake_codex(answer="seen"))
    resp = consult_mod.consult("visual", "look", images=[str(img)])
    assert resp["ok"], resp
    man = _load_manifest(resp)
    assert len(man["images"]) == 1
    rec = man["images"][0]
    assert rec["width"] == 1 and rec["height"] == 1 and len(rec["sha256"]) == 64


def test_image_evidence_rejects_missing_pillow_gracefully(_logs):
    recs, err = image_evidence([])   # no images → no error, empty records
    assert recs == [] and err is None


# --------------------------------------------------- verdict (c-7001dd4631)

_VERDICT = (
    "VERDICT\nstatus: PASS\ninspected: sha256:abc\n"
    "findings:\n- frame 3 region 10,10-40,40: dust ok\n"
    "measurements: void 72% < 0.02\ncorrections: none\nassumptions: none\n"
)


def test_verify_parses_structured_verdict(_logs, monkeypatch):
    img = _valid_png(_logs / "v.png")
    monkeypatch.setattr(consult_mod, "_run_codex", _fake_codex(answer=_VERDICT))
    resp = consult_mod.consult("visual", "verify", images=[str(img)])
    v = resp["value"]["verdict"]
    assert v["status"] == "PASS" and v["parsed"] is True
    assert "dust ok" in v["findings"]


def test_verify_absent_block_is_unverified(_logs, monkeypatch):
    img = _valid_png(_logs / "v.png")
    monkeypatch.setattr(consult_mod, "_run_codex",
                        _fake_codex(answer="looks great, ship it"))
    resp = consult_mod.consult("visual", "verify", images=[str(img)])
    assert resp["value"]["verdict"]["status"] == "UNVERIFIED"


def test_verify_pass_without_images_forced_unverified():
    v = parse_verdict(_VERDICT, images_decoded=0)
    assert v["status"] == "UNVERIFIED"


# -------------------------------------------------- boundary (c-198d217e38)

@pytest.fixture
def _ue(tmp_path, monkeypatch):
    root = tmp_path / "SpaceTravel"
    (root / "Content" / "Concepts").mkdir(parents=True)
    monkeypatch.setenv(consult_mod._UE_ROOT_ENV, str(root))
    # stub MCP discovery for the consult() calls that reach it (post-run scan tests)
    monkeypatch.setattr(consult_mod, "discover_mcp_servers",
                        lambda codex, timeout_s=30: (list(_FAKE_MCP), None))
    return root


def test_write_dir_inside_ue_rejected(_ue):
    inside = _ue / "Content" / "Meshes"
    inside.mkdir(parents=True)
    assert check_write_dir_boundary(str(inside)) is not None


def test_write_dir_equal_ue_rejected(_ue):
    assert check_write_dir_boundary(str(_ue)) is not None


def test_write_dir_parent_of_ue_rejected(_ue):
    assert check_write_dir_boundary(str(_ue.parent)) is not None


def test_write_dir_allowlisted_concepts_ok(_ue):
    ok = _ue / "Content" / "Concepts" / "batch1"
    ok.mkdir(parents=True)
    assert check_write_dir_boundary(str(ok)) is None


def test_write_dir_outside_ue_ok(_ue, tmp_path):
    outside = tmp_path / "assets"
    outside.mkdir()
    assert check_write_dir_boundary(str(outside)) is None


@pytest.mark.skipif(os.name != "nt", reason="junction is a Windows construct")
def test_write_dir_junction_into_ue_rejected(_ue, tmp_path):
    target = _ue / "Content" / "Meshes"
    target.mkdir(parents=True)
    link = tmp_path / "sneaky"
    r = subprocess.run(["cmd", "/c", "mklink", "/J", str(link), str(target)],
                       capture_output=True, text=True)
    if r.returncode != 0:
        pytest.skip(f"could not create junction: {r.stderr.strip()}")
    assert check_write_dir_boundary(str(link)) is not None   # resolved through the junction


def test_boundary_rejected_before_codex_runs(_ue, monkeypatch, tmp_path):
    monkeypatch.setenv(consult_mod._LOG_DIR_ENV, str(tmp_path / "logs"))
    monkeypatch.setattr(consult_mod, "_resolve_bin", lambda: "codex")

    def boom(argv, timeout_s):
        raise AssertionError("codex must not run when write_dir is in the UE tree")

    monkeypatch.setattr(consult_mod, "_run_codex", boom)
    resp = consult_mod.consult("creative", "gen", write_dir=str(_ue))
    assert resp["ok"] is False and resp["error"]["code"] == "boundary"


def test_read_only_profile_rejects_write_dir(_logs):
    resp = consult_mod.consult("second_opinion", "q", write_dir=str(_logs))
    assert resp["ok"] is False and "read-only" in resp["error"]["message"]


def test_post_run_scan_flags_escape_into_ue_tree(_ue, monkeypatch, tmp_path):
    monkeypatch.setenv(consult_mod._LOG_DIR_ENV, str(tmp_path / "logs"))
    monkeypatch.setattr(consult_mod, "_resolve_bin", lambda: "codex")
    outside = tmp_path / "assets"
    outside.mkdir()
    rogue = _ue / "Content" / "Meshes" / "leak.uasset"
    monkeypatch.setattr(consult_mod, "_run_codex",
                        _fake_codex(answer="done", writes_file=str(rogue)))
    resp = consult_mod.consult("build", "build", write_dir=str(outside))  # build → blender
    assert resp["ok"] is False and resp["error"]["code"] == "boundary"
    assert any("leak.uasset" in p for p in resp["value"]["escaped"])


def test_post_run_scan_ignores_allowlisted_concepts_writes(_ue, monkeypatch, tmp_path):
    # a write into the allowlisted Content/Concepts subtree (e.g. another agent's
    # concurrent concept drop) must NOT trip the boundary scan.
    monkeypatch.setenv(consult_mod._LOG_DIR_ENV, str(tmp_path / "logs"))
    monkeypatch.setattr(consult_mod, "_resolve_bin", lambda: "codex")
    outside = tmp_path / "assets"; outside.mkdir()
    allowed = _ue / "Content" / "Concepts" / "ship" / "kestrel_side.png"
    monkeypatch.setattr(consult_mod, "_run_codex",
                        _fake_codex(answer="done", writes_file=str(allowed)))
    resp = consult_mod.consult("build", "build", write_dir=str(outside))
    assert resp["ok"] is True, resp
    assert resp["value"].get("run_id")


# --------------------------------------------- write-fence remediation (S0d, c-fe4f824d82)
#
# fence_remediate(write_dir, pre_status, before_mtimes, ue_root, run_log). pre_status
# is the pre-run `git status` map (None ⇒ non-git tree). Attribution is by the run's
# codex jsonl (run_log): only a path the log NAMES is deleted/restored.

def _log_naming(*names) -> str:
    """A minimal codex `--json` stream whose shell events name each file — the
    attribution signal the fence keys on."""
    return "\n".join(json.dumps({"type": "item.completed", "item": {
        "type": "command_execution", "command": f"Set-Content {n} x"}}) for n in names)


def test_fence_deletes_log_attributed_new_file(tmp_path):
    repo = tmp_path / "ue"
    _git_init(repo)
    pre = git_status_map(repo)               # clean
    before = _snapshot_mtimes([repo])
    rogue = repo / "tools" / "helper.py"
    rogue.parent.mkdir(parents=True)
    rogue.write_text("print('leak')\n", encoding="utf-8")
    rep = fence_remediate(None, pre, before, repo, run_log=_log_naming("helper.py"))
    assert rep["git"] is True
    e = next(e for e in rep["escapes"] if _norm(rogue) == e["path"])
    assert e["action"] == "deleted_new" and e["ok"] is True and e["attribution"] == "log"
    assert e["tracked"] is False and e["pre_dirty"] is False and len(e["sha256"]) == 64
    assert not rogue.exists()                # the escaped new file is gone
    assert _real_escapes(rep) == rep["escapes"]


def test_fence_restores_log_attributed_modified_tracked_file(tmp_path):
    repo = tmp_path / "ue"
    tracked = _git_init(repo, body="original\n")
    original = tracked.read_text(encoding="utf-8")
    pre = git_status_map(repo)               # clean
    before = _snapshot_mtimes([repo])
    tracked.write_text("ROGUE OVERWRITE\n", encoding="utf-8")   # codex mutates a tracked file
    rep = fence_remediate(None, pre, before, repo, run_log=_log_naming("tracked.txt"))
    e = rep["escapes"][0]
    assert e["action"] == "restored_tracked" and e["ok"] is True and e["attribution"] == "log"
    assert e["tracked"] is True and e["pre_dirty"] is False
    assert e["pre_sha256"] != e["post_sha256"]                  # rogue vs restored differ
    assert tracked.read_text(encoding="utf-8") == original      # content is back


def test_fence_unattributed_new_file_is_left_untouched(tmp_path):
    # THE S10 fix / attribution guard: a new file appears clean→dirty during the run
    # but THIS run's codex log never names it → it is a concurrent seat's file, NOT
    # ours. It must be reported unattributed_concurrent and NEVER deleted. (c-fe4f824d82)
    repo = tmp_path / "ue"
    _git_init(repo)
    pre = git_status_map(repo)
    before = _snapshot_mtimes([repo])
    other = repo / "Source" / "seat11.cpp"
    other.parent.mkdir(parents=True)
    other.write_text("// another seat's new file\n", encoding="utf-8")
    rep = fence_remediate(None, pre, before, repo, run_log=_log_naming("something_else.py"))
    e = next(e for e in rep["escapes"] if _norm(other) == e["path"])
    assert e["action"] == "unattributed_concurrent" and e["attribution"] == "none"
    assert other.exists()                    # NOT deleted — no data loss for the other seat
    assert _real_escapes(rep) == []          # nothing attributed ⇒ run does not fail


def test_fence_no_escape_is_a_noop(tmp_path):
    repo = tmp_path / "ue"
    _git_init(repo)
    rep = fence_remediate(None, git_status_map(repo), _snapshot_mtimes([repo]), repo)
    assert rep["git"] is True and rep["escapes"] == [] and rep["note"] == ""


def test_fence_pre_dirty_wins_over_log_attribution(tmp_path):
    # another seat's IN-PROGRESS edit is dirty before the run; even if this run's log
    # happens to name the same basename, pre-dirty precedence means it is NEVER
    # reverted. (c-1457650970 second attribution signal)
    repo = tmp_path / "ue"
    tracked = _git_init(repo, body="original\n")
    tracked.write_text("ANOTHER SEAT WIP\n", encoding="utf-8")   # dirty BEFORE the run
    pre = git_status_map(repo)                                   # captures it as dirty
    before = _snapshot_mtimes([repo])
    tracked.write_text("ANOTHER SEAT WIP 2\n", encoding="utf-8")  # still churning during the run
    rep = fence_remediate(None, pre, before, repo, run_log=_log_naming("tracked.txt"))
    e = next(e for e in rep["escapes"] if _norm(tracked) == e["path"])
    assert e["action"] == "pre_dirty_concurrent" and e["pre_dirty"] is True
    assert tracked.read_text(encoding="utf-8") == "ANOTHER SEAT WIP 2\n"  # NOT reverted
    assert _real_escapes(rep) == []                              # not a run-failing escape


def test_fence_gitignored_build_outputs_never_escape(tmp_path):
    # Binaries/Intermediate/Saved are gitignored → git status omits them → the fence
    # never sees them as escapes even when written during the run. (c-1457650970)
    repo = tmp_path / "ue"
    _git_init(repo)
    (repo / ".gitignore").write_text("Binaries/\nIntermediate/\nSaved/\n", encoding="utf-8")
    subprocess.run(["git", "-C", str(repo), "add", ".gitignore"], check=True,
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    subprocess.run(["git", "-C", str(repo), "-c", "user.email=t@e.st", "-c", "user.name=test",
                    "commit", "-q", "-m", "ignore"], check=True,
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    pre = git_status_map(repo)
    before = _snapshot_mtimes([repo])
    (repo / "Binaries" / "Win64").mkdir(parents=True)
    (repo / "Binaries" / "Win64" / "UE.dll").write_bytes(b"\x00" * 16)
    rep = fence_remediate(None, pre, before, repo, run_log=_log_naming("UE.dll"))
    assert rep["escapes"] == [] and _real_escapes(rep) == []
    assert (repo / "Binaries" / "Win64" / "UE.dll").exists()     # build output untouched


def test_fence_non_git_root_falls_back_to_delete_new_only(tmp_path):
    plain = tmp_path / "not_a_repo"
    plain.mkdir()
    assert git_status_map(plain) is None      # not a git repo
    pre = plain / "pre.txt"
    pre.write_text("keep\n", encoding="utf-8")
    before = _snapshot_mtimes([plain])        # `pre` is pre-existing, the others are not
    newf = plain / "leak.py"
    newf.write_text("rogue\n", encoding="utf-8")
    unattributed = plain / "seat11.tmp"
    unattributed.write_text("another seat\n", encoding="utf-8")
    pre.write_text("mutated\n", encoding="utf-8")
    # bump mtime deterministically — Windows mtime resolution can collapse two
    # same-tick writes, and the non-git fallback has only the mtime signal
    st = pre.stat()
    os.utime(pre, ns=(st.st_atime_ns, st.st_mtime_ns + 5_000_000_000))
    rep = fence_remediate(None, None, before, plain, run_log=_log_naming("leak.py", "pre.txt"))
    assert rep["git"] is False and "not a git repo" in rep["note"]
    by_path = {e["path"]: e for e in rep["escapes"]}
    assert by_path[_norm(newf)]["action"] == "deleted_new" and not newf.exists()
    assert by_path[_norm(pre)]["action"] == "left_modified_no_git" and pre.exists()
    # a new file the log never named is left untouched even in the non-git fallback
    assert by_path[_norm(unattributed)]["action"] == "unattributed_concurrent"
    assert unattributed.exists()


# --------------------------------------------- recovered envelope (S0d, c-16ae18056e)

@pytest.fixture
def _ue_git(tmp_path, monkeypatch):
    """A UE root that IS a git repo, with a committed tracked file and the
    Content/Concepts allowlist; MCP discovery + bin stubbed like _logs/_ue."""
    root = tmp_path / "SpaceTravel"
    (root / "Content" / "Concepts").mkdir(parents=True)
    _git_init(root)
    monkeypatch.setenv(consult_mod._LOG_DIR_ENV, str(tmp_path / "logs"))
    monkeypatch.setenv(consult_mod._UE_ROOT_ENV, str(root))
    monkeypatch.setattr(consult_mod, "_resolve_bin", lambda: "codex")
    monkeypatch.setattr(consult_mod, "discover_mcp_servers",
                        lambda codex, timeout_s=30: (list(_FAKE_MCP), None))
    return root


def test_consult_recovers_answer_and_deletes_new_escape(_ue_git, monkeypatch, tmp_path):
    outside = tmp_path / "assets"
    outside.mkdir()
    rogue = _ue_git / "tools" / "build_selection_sheet.py"   # the origin-run escape shape
    monkeypatch.setattr(consult_mod, "_run_codex",
                        _fake_codex(answer="here is your spec", thread="tid-keep",
                                    writes_file=str(rogue)))
    resp = consult_mod.consult("build", "spec", write_dir=str(outside))  # build → blender
    assert resp["ok"] is False and resp["error"]["code"] == "boundary"
    val = resp["value"]
    assert val["recovered"] is True                       # answer preserved, not discarded
    assert val["answer"] == "here is your spec"
    assert val["thread_id"] == "tid-keep"                 # thread preserved
    assert any(e["action"] == "deleted_new" for e in val["escapes"])
    assert not rogue.exists()                             # the rogue file was removed
    man = _load_manifest(resp)
    assert man["status"] == "boundary_violation" and man["fence"]["git"] is True


def test_consult_recovers_answer_and_restores_tracked_escape(_ue_git, monkeypatch, tmp_path):
    outside = tmp_path / "assets"
    outside.mkdir()
    tracked = _ue_git / "tracked.txt"
    original = tracked.read_text(encoding="utf-8")
    monkeypatch.setattr(consult_mod, "_run_codex",
                        _fake_codex(answer="done", writes_file=str(tracked)))
    resp = consult_mod.consult("build", "spec", write_dir=str(outside))
    assert resp["ok"] is False and resp["error"]["code"] == "boundary"
    assert resp["value"]["recovered"] is True
    assert any(e["action"] == "restored_tracked" for e in resp["value"]["escapes"])
    assert tracked.read_text(encoding="utf-8") == original   # git checkout -- restored it


def test_consult_concurrent_seat_write_does_not_fail_the_run(_ue_git, monkeypatch):
    # The S10 regression, end to end: another seat's edit is dirty in the UE tree
    # before a text-only consult that writes nothing. The run must NOT be rejected;
    # the answer comes back with recovered=true and the path attributed concurrent,
    # and the concurrent edit is left intact. (c-1457650970)
    tracked = _ue_git / "tracked.txt"
    tracked.write_text("SEAT-11 WORK IN PROGRESS\n", encoding="utf-8")  # concurrent, pre-run
    monkeypatch.setattr(consult_mod, "_run_codex",
                        _fake_codex(answer="text-only advice", thread="tid-x"))
    resp = consult_mod.consult("second_opinion", "advise")   # design profile, no write_dir
    assert resp["ok"] is True                                 # NOT rejected — the S10 fix
    val = resp["value"]
    assert val["answer"] == "text-only advice"
    assert val["recovered"] is True
    assert any("tracked.txt" in p for p in val["concurrent"])
    assert tracked.read_text(encoding="utf-8") == "SEAT-11 WORK IN PROGRESS\n"  # left intact
    man = _load_manifest(resp)
    assert man["status"] == "ok_concurrent_writes"
    assert man["writes_outside_write_dir"] == []             # no real escape recorded


def test_consult_unattributed_new_file_during_run_does_not_fail(_ue_git, monkeypatch):
    # A concurrent seat drops a NEW file into the UE tree DURING the run; this run's
    # codex log never names it. It must be left untouched and the run must succeed —
    # the log-attribution guard, end to end. (c-fe4f824d82)
    concurrent = _ue_git / "Source" / "seat11_new.cpp"

    def fake(argv, timeout_s):
        concurrent.parent.mkdir(parents=True, exist_ok=True)
        concurrent.write_text("// seat 11's file\n", encoding="utf-8")   # not in the log
        Path(argv[argv.index("-o") + 1]).write_text("text advice", encoding="utf-8")
        return json.dumps({"type": "thread.started", "thread_id": "t"}) + "\n", 0, False

    monkeypatch.setattr(consult_mod, "_run_codex", fake)
    resp = consult_mod.consult("second_opinion", "advise")
    assert resp["ok"] is True                                # not attributed to us → not rejected
    assert resp["value"]["recovered"] is True
    assert any("seat11_new.cpp" in p for p in resp["value"]["concurrent"])
    assert concurrent.exists()                               # NOT deleted (no data loss)
