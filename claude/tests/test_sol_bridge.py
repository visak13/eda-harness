"""The Sol (GPT / codex CLI) bridge — engine, tool wiring, and gpt-image removal.

The bar this pins, and WHY each half exists:

* The ENGINE is deterministic (tools/sol_bridge.py). Its job is to make the five
  Codex-CLI landmines and the binary trap un-hittable by a shell. So the tests
  that matter most are on the PURE functions — argv order, the `-i`/`--` variadic
  termination, the resume shape, the code-tree write guard, the binary-sibling
  selection, and thread stickiness — each asserted against the exact failure it
  prevents (SOL-BRIDGE.md §2). None of these call Sol.

* run_sol's ORCHESTRATION (resume-vs-fresh, non-zero-exit-is-a-blocker,
  host-error detection, thread persistence) is driven with a monkeypatched
  subprocess so the contract is pinned without spending the user's ChatGPT quota.

* The WIRING: both tools registered, role-scoped (author->worker, consult->
  consult), neuron derives both.

* The REMOVAL: gpt-image is gone from every live surface, atomically with the
  s26 allowlist entry it required.

No `re` (coding-standard #7); every assertion is Python.
"""

import json
from pathlib import Path

import pytest

from edp_claude.tools import sol_bridge as sb


# ══════════════════════════════════════════════════════════════════════════
# argv construction — the landmine-safe forms (PURE)
# ══════════════════════════════════════════════════════════════════════════
_BASE = dict(workdir="C:/ws", sandbox="workspace-write",
             last_message_file="C:/ws/lm.txt")


def test_fresh_no_images_prompt_is_behind_double_dash():
    """A brief that starts with '-' must never be parsed as a flag: the prompt is
    ALWAYS the last positional behind `--`, images or not."""
    argv = sb.build_argv("CODEX", prompt="-weird brief", **_BASE)
    assert argv[0] == "CODEX" and argv[1] == "exec"
    assert argv[-2:] == ["--", "-weird brief"]
    # the exec globals are present and BEFORE any positional
    for flag in ("--skip-git-repo-check", "-C", "-s", "--json", "-o"):
        assert flag in argv


def test_fresh_with_images_terminates_the_variadic_before_the_prompt():
    """Landmine 0: `-i` is variadic on a fresh turn and WILL eat the prompt unless
    `--` ends it. The prompt must land as the positional, not a second image."""
    argv = sb.build_argv("CODEX", prompt="P", images=["a.png", "b.png"], **_BASE)
    i = argv.index("-i")
    assert argv[i:i + 3] == ["-i", "a.png", "b.png"]
    assert argv[i + 3] == "--"          # variadic terminated
    assert argv[-1] == "P"              # prompt is the positional, not an image
    assert argv.count("--") == 1


def test_resume_puts_image_after_subcommand_and_positionals_after_dashdash():
    """Landmine 2 + the resume shape: exec globals BEFORE `resume`; `-i` is
    per-flag on resume and attaches to the post-resume prompt, so it sits AFTER
    the subcommand; then `-- <thread_id> <prompt>`."""
    argv = sb.build_argv("CODEX", prompt="next", images=["r.png"],
                         resume_thread="TID-1", **_BASE)
    r = argv.index("resume")
    assert "-C" in argv[:r] and "-s" in argv[:r]     # globals before subcommand
    assert argv[r:] == ["resume", "-i", "r.png", "--", "TID-1", "next"]


def test_resume_two_images_repeat_the_flag_not_a_variadic():
    """resume's `-i` is single-value; multiple images repeat the flag (no `--`
    swallow risk, but the terminator is still emitted for the positionals)."""
    argv = sb.build_argv("CODEX", prompt="n", images=["a.png", "b.png"],
                         resume_thread="T", **_BASE)
    r = argv.index("resume")
    assert argv[r:] == ["resume", "-i", "a.png", "-i", "b.png", "--", "T", "n"]


def test_effort_becomes_a_config_override():
    argv = sb.build_argv("CODEX", prompt="p", effort="high", **_BASE)
    j = argv.index("-c")
    assert argv[j + 1] == "model_reasoning_effort=high"


def test_bad_sandbox_is_refused():
    with pytest.raises(sb.SolBridgeError):
        sb.build_argv("CODEX", prompt="p", workdir="C:/ws",
                      sandbox="yolo", last_message_file="C:/ws/lm.txt")


# ══════════════════════════════════════════════════════════════════════════
# code-tree write guard — Sol authors assets, NEVER code
# ══════════════════════════════════════════════════════════════════════════
def test_asset_dir_inside_a_protected_code_root_is_refused(monkeypatch, tmp_path):
    root = tmp_path / "myrepo"
    (root / "assets").mkdir(parents=True)
    monkeypatch.setenv("EDP_SOL_CODE_ROOTS", str(root))
    with pytest.raises(sb.SolBridgeError) as e:
        sb.refuse_code_tree(str(root / "assets"))
    assert "code tree" in str(e.value)


def test_asset_dir_with_a_source_segment_is_refused(tmp_path):
    # 'src' anywhere in the path means "code", not "asset"
    d = tmp_path / "proj" / "src" / "gen"
    with pytest.raises(sb.SolBridgeError) as e:
        sb.refuse_code_tree(str(d))
    assert "source directory" in str(e.value)


def test_relative_asset_dir_is_refused():
    with pytest.raises(sb.SolBridgeError):
        sb.refuse_code_tree("relative/assets")


def test_the_framework_repo_itself_is_always_protected():
    # the default roots protect the edp framework tree without any env set
    with pytest.raises(sb.SolBridgeError):
        sb.refuse_code_tree(r"C:\Projects\Learning\eda-base3\claude\src\edp_claude")


def test_a_legit_asset_dir_outside_code_is_accepted(tmp_path):
    d = tmp_path / "nightsky" / "assets" / "textures"
    got = sb.refuse_code_tree(str(d))
    assert got == d.resolve()


# ══════════════════════════════════════════════════════════════════════════
# binary selection — the .sandbox-bin trap (talk-but-cannot-write)
# ══════════════════════════════════════════════════════════════════════════
def _make_codex(dirpath: Path, with_sibling: bool) -> Path:
    dirpath.mkdir(parents=True, exist_ok=True)
    exe = dirpath / "codex.exe"
    exe.write_text("stub", encoding="utf-8")
    if with_sibling:
        (dirpath / "codex-code-mode-host.exe").write_text("stub", encoding="utf-8")
    return exe


def test_override_with_host_sibling_is_accepted(monkeypatch, tmp_path):
    exe = _make_codex(tmp_path / "good", with_sibling=True)
    monkeypatch.setenv("EDP_SOL_CODEX_BIN", str(exe))
    assert sb.resolve_codex_binary() == exe


def test_override_without_host_sibling_is_refused(monkeypatch, tmp_path):
    """The exact trap: the copy that talks to Sol but cannot let it WRITE. It
    looks right in every way except the missing sibling — so the sibling IS the
    selection rule."""
    exe = _make_codex(tmp_path / "sandbox-bin", with_sibling=False)
    monkeypatch.setenv("EDP_SOL_CODEX_BIN", str(exe))
    with pytest.raises(sb.SolBridgeError) as e:
        sb.resolve_codex_binary()
    assert "code-mode-host" in str(e.value)


def test_override_missing_file_is_refused(monkeypatch, tmp_path):
    monkeypatch.setenv("EDP_SOL_CODEX_BIN", str(tmp_path / "nope.exe"))
    with pytest.raises(sb.SolBridgeError):
        sb.resolve_codex_binary()


def test_path_codex_beats_codex_home(monkeypatch, tmp_path):
    """The npm CLI on PATH is the copy update-claude.bat keeps current, so it
    wins over the app-bundled copy (which lags and is refused newer models).
    `which` returns the npm .cmd shim; the resolver must hand back the REAL exe
    with the host beside it, never the shim."""
    monkeypatch.delenv("EDP_SOL_CODEX_BIN", raising=False)
    _make_codex(tmp_path / "home" / "plugins" / ".plugin-appserver",
                with_sibling=True)
    monkeypatch.setenv("CODEX_HOME", str(tmp_path / "home"))
    npm = tmp_path / "npm"
    npm.mkdir()
    (npm / "codex.cmd").write_text("@echo off", encoding="utf-8")
    real = _make_codex(npm / "node_modules" / "@openai" / "codex-win32-x64"
                       / "vendor" / "x86_64-pc-windows-msvc" / "bin",
                       with_sibling=True)
    monkeypatch.setattr(sb.shutil, "which",
                        lambda name: str(npm / "codex.cmd") if name == "codex" else None)
    assert sb.resolve_codex_binary() == real


def test_path_shim_without_real_exe_is_skipped(monkeypatch, tmp_path):
    monkeypatch.delenv("EDP_SOL_CODEX_BIN", raising=False)
    good = _make_codex(tmp_path / "home" / "plugins" / ".plugin-appserver",
                       with_sibling=True)
    monkeypatch.setenv("CODEX_HOME", str(tmp_path / "home"))
    (tmp_path / "codex.cmd").write_text("@echo off", encoding="utf-8")
    monkeypatch.setattr(sb.shutil, "which",
                        lambda name: str(tmp_path / "codex.cmd") if name == "codex" else None)
    assert sb.resolve_codex_binary() == good


def test_autoresolve_scans_codex_home_for_the_copy_with_the_sibling(
        monkeypatch, tmp_path):
    monkeypatch.delenv("EDP_SOL_CODEX_BIN", raising=False)
    monkeypatch.setattr(sb.shutil, "which", lambda name: None)
    # a broken copy and a good copy under the same CODEX_HOME
    _make_codex(tmp_path / ".sandbox-bin", with_sibling=False)
    good = _make_codex(tmp_path / "plugins" / ".plugin-appserver",
                       with_sibling=True)
    monkeypatch.setenv("CODEX_HOME", str(tmp_path))
    assert sb.resolve_codex_binary() == good


# ══════════════════════════════════════════════════════════════════════════
# thread stickiness — one thread per (caller, advisor); advisors don't mix
# ══════════════════════════════════════════════════════════════════════════
def test_thread_store_round_trips_per_caller_advisor(monkeypatch, tmp_path):
    monkeypatch.setenv("EDP_SOL_THREADS_FILE", str(tmp_path / "threads.json"))
    assert sb.load_thread("plan-1:a1", "sol") is None
    sb.save_thread("plan-1:a1", "sol", "TID-A", "C:/ws")
    assert sb.load_thread("plan-1:a1", "sol") == "TID-A"


def test_distinct_advisors_hold_distinct_threads(monkeypatch, tmp_path):
    """A long role can use MULTIPLE advisors so context is not cross-polluted:
    the key is (caller, advisor), so two advisors never collide."""
    monkeypatch.setenv("EDP_SOL_THREADS_FILE", str(tmp_path / "t.json"))
    sb.save_thread("plan-1:a1", "sol", "TID-SOL", "C:/ws")
    sb.save_thread("plan-1:a1", "critic", "TID-CRITIC", "C:/ws")
    assert sb.load_thread("plan-1:a1", "sol") == "TID-SOL"
    assert sb.load_thread("plan-1:a1", "critic") == "TID-CRITIC"


def test_thread_key_is_caller_and_advisor():
    assert sb.thread_key("h", "sol") == "h|sol"
    assert sb.thread_key("", "") == "anon|sol"


# ══════════════════════════════════════════════════════════════════════════
# event parsing — defensive, never raises, extracts what matters
# ══════════════════════════════════════════════════════════════════════════
def test_parse_extracts_thread_id_messages_and_tolerates_garbage():
    stream = "\n".join([
        '{"type": "thread.started", "thread_id": "019f-abc"}',
        "not json at all",
        '{"type": "item.completed", "item": {"type": "agent_message", '
        '"text": "here is the asset"}}',
        '{"type": "item.completed", "item": {"type": "file_change", '
        '"path": "C:/ws/tree.glb"}}',
        '{"type": "turn.completed"}',
    ])
    out = sb.parse_events(stream)
    assert out["thread_id"] == "019f-abc"
    assert "here is the asset" in out["messages"]
    assert "C:/ws/tree.glb" in out["files"]
    assert out["host_error"] is False


def test_parse_flags_the_code_mode_host_router_error():
    """The silent failure: the router error goes to stderr, never to -o. We merge
    stderr into the stream precisely so this is visible."""
    stream = ('ERROR codex_core::tools::router: error=failed to spawn '
              'code-mode host C:\\...\\codex-code-mode-host.exe')
    out = sb.parse_events(stream)
    assert out["host_error"] is True


# ══════════════════════════════════════════════════════════════════════════
# run_sol orchestration — driven with a fake subprocess (no Sol, no quota)
# ══════════════════════════════════════════════════════════════════════════
class _FakeProc:
    def __init__(self, stdout, returncode):
        self.stdout = stdout
        self.returncode = returncode


def _wire_fake_sol(monkeypatch, tmp_path, stdout, returncode):
    monkeypatch.setattr(sb, "resolve_codex_binary", lambda: Path("CODEX"))
    monkeypatch.setenv("EDP_SOL_THREADS_FILE", str(tmp_path / "threads.json"))

    calls = {}

    def fake_run(argv, **kw):
        calls["argv"] = argv
        calls["stdin"] = kw.get("stdin")
        # the -o last-message file is written by codex; emulate it
        oi = argv.index("-o")
        Path(argv[oi + 1]).write_text("Sol says done", encoding="utf-8")
        return _FakeProc(stdout, returncode)

    monkeypatch.setattr(sb.subprocess, "run", fake_run)
    return calls


def test_run_sol_success_persists_the_thread_and_returns_ok(monkeypatch, tmp_path):
    work = tmp_path / "assets"
    stdout = '{"type":"thread.started","thread_id":"TID-NEW"}\n'
    calls = _wire_fake_sol(monkeypatch, tmp_path, stdout, 0)

    run = sb.run_sol(prompt="make a tree", workdir=str(work),
                     sandbox="workspace-write", caller="plan-1:a1", advisor="sol")
    assert run.ok and run.exit_code == 0
    assert run.thread_id == "TID-NEW"
    assert run.last_message == "Sol says done"
    assert run.error is None
    # stdin was empty (DEVNULL) — the mandatory EOF that stops the hang
    assert calls["stdin"] == sb.subprocess.DEVNULL
    # the thread was persisted, so the NEXT call resumes it
    assert sb.load_thread("plan-1:a1", "sol") == "TID-NEW"


def test_run_sol_resumes_a_known_thread(monkeypatch, tmp_path):
    work = tmp_path / "assets"
    calls = _wire_fake_sol(monkeypatch, tmp_path, '{"type":"turn.completed"}\n', 0)
    sb.save_thread("plan-1:a1", "sol", "TID-EXISTING", str(work))

    sb.run_sol(prompt="tweak it", workdir=str(work), sandbox="workspace-write",
               caller="plan-1:a1", advisor="sol")
    assert "resume" in calls["argv"]
    assert "TID-EXISTING" in calls["argv"]


def test_run_sol_new_thread_flag_ignores_the_sticky_thread(monkeypatch, tmp_path):
    work = tmp_path / "assets"
    calls = _wire_fake_sol(monkeypatch, tmp_path, '{"type":"turn.completed"}\n', 0)
    sb.save_thread("plan-1:a1", "sol", "TID-OLD", str(work))

    sb.run_sol(prompt="fresh start", workdir=str(work), sandbox="workspace-write",
               caller="plan-1:a1", advisor="sol", new_thread=True)
    assert "resume" not in calls["argv"]


def test_run_sol_nonzero_exit_is_a_blocker_never_a_silent_success(
        monkeypatch, tmp_path):
    """The user's hard rule: non-zero exit is a first-class blocker. ok=False and
    a blocker message the tool must surface upward — never a retry."""
    calls = _wire_fake_sol(monkeypatch, tmp_path, "", 1)
    run = sb.run_sol(prompt="p", workdir=str(tmp_path / "a"),
                     sandbox="workspace-write", caller="c", advisor="sol")
    assert run.ok is False
    assert run.exit_code == 1
    assert run.error and "blocker" in run.error.lower()
    assert "retry" in run.error.lower()


def test_run_sol_detects_the_wrong_binary_host_error(monkeypatch, tmp_path):
    stdout = ("ERROR codex_core::tools::router: error=failed to spawn "
              "code-mode host\n")
    _wire_fake_sol(monkeypatch, tmp_path, stdout, 0)
    run = sb.run_sol(prompt="p", workdir=str(tmp_path / "a"),
                     sandbox="workspace-write", caller="c", advisor="sol")
    assert run.ok is False
    assert "code-mode host" in run.error


# ── preconditions that fire BEFORE any subprocess (no binary needed) ────────
def test_empty_prompt_refused():
    with pytest.raises(sb.SolBridgeError):
        sb.run_sol(prompt="  ", workdir="C:/x", sandbox="read-only", caller="c")


def test_oversized_prompt_refused():
    with pytest.raises(sb.SolBridgeError) as e:
        sb.run_sol(prompt="x" * 40000, workdir="C:/x", sandbox="read-only",
                   caller="c")
    assert "bytes" in str(e.value)


def test_missing_image_is_a_hard_error(tmp_path):
    with pytest.raises(sb.SolBridgeError) as e:
        sb.run_sol(prompt="p", workdir=str(tmp_path), sandbox="read-only",
                   caller="c", images=[str(tmp_path / "nope.png")])
    assert "does not exist" in str(e.value)


# ══════════════════════════════════════════════════════════════════════════
# tool wiring — RETIRED (2026-08-12 dead-surface sweep). The direct verbs
# (sol_author_asset / sol_consult) were superseded by the provider-bridge
# delegates (delegate_generate / consult_external, tools/bridge.py) and their
# classes deleted. The ENGINE above is untouched: bridge.py drives
# sol_bridge.run_sol as its `cli` backend, which is what this file's engine
# half keeps proving. What is worth pinning now is that the retirement is
# total (a half-deleted verb is the d14 regression class) and that the
# bridge really still reaches the engine.
# ══════════════════════════════════════════════════════════════════════════
def test_the_direct_sol_verbs_are_retired_everywhere():
    from edp_claude.tools._tools import ALL_TOOL_CLASSES
    from edp_claude.tools.catalog import TOOL_ONE_LINERS
    from edp_claude.tools.roles import RETIRED_VERBS, ROLE_TOOLSETS
    names = {c.name for c in ALL_TOOL_CLASSES}
    for verb in ("sol_author_asset", "sol_consult"):
        assert verb not in names, f"{verb} is back in the registry"
        assert verb not in TOOL_ONE_LINERS, f"{verb} has a catalog line again"
        assert verb in RETIRED_VERBS, f"{verb} missing from RETIRED_VERBS"
        for role, toolset in ROLE_TOOLSETS.items():
            assert verb not in toolset, f"{role} grants retired {verb}"
    # POSITIVE CONTROL: the successors are registered and scoped.
    assert {"delegate_generate", "consult_external"} <= names
    assert "delegate_generate" in ROLE_TOOLSETS["worker"]
    assert "consult_external" in ROLE_TOOLSETS["curiosity"]


def test_the_bridge_still_drives_the_sol_engine():
    """The engine survives the verbs: bridge.py's `cli` backend runs turns
    through sol_bridge.run_sol (the module under test here)."""
    import inspect

    from edp_claude.tools import bridge
    src = inspect.getsource(bridge)
    assert "sol_bridge" in src and "run_sol" in src


def test_no_live_guide_instructs_the_retired_sol_verbs():
    root = Path(__file__).resolve().parents[1]
    corpus = (sorted((root / ".claude" / "commands").glob("*.md"))
              + sorted((root / "docs" / "guides").glob("*.md")))
    for path in corpus:
        text = path.read_text(encoding="utf-8")
        for verb in ("sol_author_asset(", "sol_consult("):
            assert verb not in text, f"{path.name} still calls {verb}...)"


# ══════════════════════════════════════════════════════════════════════════
# gpt-image removal — gone from every LIVE surface, atomically
# ══════════════════════════════════════════════════════════════════════════
_ROOT = Path(__file__).resolve().parents[1]


def test_gpt_image_server_script_is_deleted():
    assert not (_ROOT / "scripts" / "gpt_image_mcp.py").exists()


def test_mcp_json_has_no_gpt_image_server():
    cfg = json.loads((_ROOT / ".mcp.json").read_text(encoding="utf-8"))
    assert "gpt-image" not in cfg.get("mcpServers", {})


def test_no_generate_image_allowlist_entry_remains():
    from test_s26_guide_tool_names import NON_TOOL_CALL_FORMS
    assert "generate_image" not in NON_TOOL_CALL_FORMS


def test_worker_guide_no_longer_calls_generate_image():
    from test_s26_guide_tool_names import snake_call_forms
    worker = (_ROOT / ".claude" / "commands" / "worker.md").read_text(
        encoding="utf-8")
    assert "generate_image" not in snake_call_forms(worker)
    assert "gpt-image" not in worker
