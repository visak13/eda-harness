"""S9 (epic-0cec8d1c31, s-8ca20e8543): the guides folder holds only what seats use; get_guide indexes it and
refuses path tricks; it resolves on a hermetic board whose agent home has no guides (p-13172d54)."""
from __future__ import annotations

import re
from pathlib import Path

import pytest

from edp8 import guides, settings
from edp8.bundles import GetGuideArgs, _get_guide

V8 = Path(__file__).resolve().parents[1]
GUIDES = V8 / "guides"

WORKING_RULES = {"shared-host-rules", "agent-tools", "resume", "context-refresh", "design-template", "codex-images",
                 "strategy-creative-reference-then-build"}
RUNBOOKS = {f"troubleshooting-{n}" for n in ("broker-dead-mail", "caps-saturated", "feed-lag", "harness-login", "mcp-401",
                                             "pool-port-exhaustion", "service-down", "stuck-ticket", "update-failed")}
OPERATOR = {"code-tab-faq", "tailnet-public-mode", "remote-access", "edp-ps1", "http-upload-policy", "pi-seat", "harness-parity"}
ORPHANS = {"diagnose-with-logs-and-traces", "ll-python-craft", "poc-then-iterate", "refactor-in-steps",
           "research-then-build", "walking-skeleton"}


@pytest.fixture(autouse=True)
def _checkout_home(monkeypatch):
    monkeypatch.setenv("EDP_HOME", str(V8))
    monkeypatch.delenv("EDP_AGENT_HOME", raising=False)


def call(name=None):
    return _get_guide(GetGuideArgs(name=name))


def test_folder_holds_exactly_the_working_rules_and_runbooks():
    assert {p.stem for p in GUIDES.glob("*.md")} == WORKING_RULES | RUNBOOKS
    assert [p for p in GUIDES.iterdir() if p.is_dir()] == []


def test_operator_docs_runtime_data_and_history_moved():
    for n in OPERATOR:
        assert (V8 / "docs" / "operator" / f"{n}.md").is_file(), n
    assert (V8 / "docs" / "operator" / "harness-parity" / "wording.json").is_file()
    assert (V8 / "src" / "edp8" / "codex_seat" / "descriptions.ours.json").is_file()
    assert (V8 / "docs" / "evidence" / "astra-seat.md").is_file()
    assert not (GUIDES / "astra-seat.md").exists() and not (GUIDES / "feed-format.md").exists()


def test_orphan_strategy_files_are_gone_and_creative_one_stays():
    for n in ORPHANS:
        assert not (GUIDES / f"strategy-{n}.md").exists(), n
    assert (GUIDES / "strategy-creative-reference-then-build.md").is_file()


def test_no_consult_or_sol_pairing_text_in_guides():
    for p in GUIDES.glob("*.md"):
        text = p.read_text(encoding="utf-8")
        assert not re.search(r"\bconsult\b|\bSol\b|review"+"er role", text, re.I), p.name


def test_index_lists_every_guide_with_purpose_and_size():
    out = call()
    assert out["ok"] is True
    rows = out["value"]["guides"]
    assert {r["name"] for r in rows} == WORKING_RULES | RUNBOOKS
    assert all(r["purpose"] and r["kb"] > 0 for r in rows)
    assert next(r for r in rows if r["name"] == "resume")["purpose"].startswith("Resume")


def test_fetch_one_guide():
    out = call("shared-host-rules")
    assert out["ok"] is True and out["value"]["body"].startswith("# Shared-host rules")


@pytest.mark.parametrize("bad", ["../x", "..", "a/b", "a\\b", "C:foo", "C:\\Windows\\win", "/etc/passwd", "shared-host-rules.md",
                                 "", " resume", "resume\n", "a..b", "\\\\host\\share\\x"])
def test_path_tricks_are_refused_before_the_filesystem(bad, monkeypatch):
    monkeypatch.setattr(guides, "_files", lambda: pytest.fail("touched the filesystem"))
    out = call(bad)
    assert out["ok"] is False and out["error"]["code"] == "invalid_name"
    assert "get_guide() lists" in out["hint"]


def test_unknown_name_names_the_allowed_ones():
    out = call("nope")
    assert out["ok"] is False and out["error"]["code"] == "not_found"
    assert "shared-host-rules" in out["error"]["allowed"]


def test_hermetic_home_without_guides_still_serves_the_packaged_ones(tmp_path, monkeypatch):
    # p-13172d54 (+ p-3836c51f, p-06664d53): a drill board's agent home has no guides/ folder
    monkeypatch.setattr(settings, "agent_home", lambda: tmp_path / "empty-home")
    out = call("shared-host-rules")
    assert out["ok"] is True and "Shared-host rules" in out["value"]["body"]
    assert any(r["name"] == "resume" for r in call()["value"]["guides"])


def test_a_home_copy_wins_over_the_packaged_one(tmp_path, monkeypatch):
    (tmp_path / "guides").mkdir()
    (tmp_path / "guides" / "resume.md").write_text("# Resume — edited\n", encoding="utf-8")
    monkeypatch.setattr(settings, "agent_home", lambda: tmp_path)
    assert call("resume")["value"]["body"] == "# Resume — edited\n"


def test_a_retired_guide_left_in_an_existing_home_is_neither_listed_nor_served(tmp_path, monkeypatch):
    g = tmp_path / "guides"
    g.mkdir()
    for old in ("poc-then-iterate", "feed-format", "astra-seat"):
        (g / f"{old}.md").write_text(f"# {old}\n", encoding="utf-8")
    (g / "resume.md").write_text("# Resume — edited\n", encoding="utf-8")
    monkeypatch.setattr(settings, "agent_home", lambda: tmp_path)
    names = {r["name"] for r in call()["value"]["guides"]}
    assert not names & {"poc-then-iterate", "feed-format", "astra-seat"} and "resume" in names
    assert call("feed-format")["ok"] is False
    assert call("resume")["value"]["body"] == "# Resume — edited\n"


def test_a_guide_file_that_is_a_symlink_is_skipped(tmp_path, monkeypatch):
    g = tmp_path / "guides"
    g.mkdir()
    (g / "resume.md").write_text("# planted\n", encoding="utf-8")
    monkeypatch.setattr(settings, "agent_home", lambda: tmp_path)
    monkeypatch.setattr(Path, "is_symlink", lambda self: self.name == "resume.md" and self.parent == g)
    assert "planted" not in call("resume")["value"]["body"]


def test_a_symlinked_guide_file_is_refused(tmp_path, monkeypatch):
    outside = tmp_path / "secret.md"
    outside.write_text("# secret\n", encoding="utf-8")
    g = tmp_path / "home" / "guides"
    g.mkdir(parents=True)
    try:
        (g / "resume.md").symlink_to(outside)
    except OSError:
        pytest.skip("symlinks need privileges on this host")
    monkeypatch.setattr(settings, "agent_home", lambda: tmp_path / "home")
    out = call("resume")  # the symlink is skipped, so the packaged resume guide answers
    assert out["ok"] is True and "secret" not in out["value"]["body"]


def test_symlink_or_nested_file_in_the_home_is_not_listed(tmp_path, monkeypatch):
    g = tmp_path / "guides"
    (g / "sub").mkdir(parents=True)
    (g / "sub" / "hidden.md").write_text("# hidden\n", encoding="utf-8")
    (g / "bad.name.md").write_text("# dotted\n", encoding="utf-8")
    monkeypatch.setattr(settings, "agent_home", lambda: tmp_path)
    names = {r["name"] for r in call()["value"]["guides"]}
    assert "hidden" not in names and "bad.name" not in names


def test_every_guide_named_in_a_card_skill_or_source_exists():
    pat = re.compile(r"get_guide\(\s*(?:name=)?['\"]([A-Za-z0-9_-]+)['\"]")
    named: set[str] = set()
    for root in (V8 / ".claude", V8 / "src" / "edp8", V8 / "guides"):
        for p in root.rglob("*"):
            if p.suffix in {".md", ".py"} and p.is_file():
                named |= set(pat.findall(p.read_text(encoding="utf-8", errors="ignore")))
    named -= {"troubleshooting-<class>", "x"}
    assert named <= WORKING_RULES | RUNBOOKS, named - (WORKING_RULES | RUNBOOKS)


def test_tool_contract_guide_links_resolve():
    from edp8.tool_contracts import LOCAL_OBJECTS
    for obj, row in LOCAL_OBJECTS.items():
        for g in row["guides"]:
            assert g in WORKING_RULES | RUNBOOKS, (obj, g)


def test_served_operator_docs_ship_in_the_wheel_config():
    text = (V8 / "pyproject.toml").read_text(encoding="utf-8")
    for n in ("code-tab-faq", "remote-access"):
        assert f'"docs/operator/{n}.md" = "edp8/operator_docs/{n}.md"' in text
        assert f'"docs/operator/{n}.md",' in text.split("only-include", 1)[1]
