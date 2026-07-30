"""W15 (DESIGN-v6) — orchestrator spec->guide revert.

ROOT CAUSE: the orchestrator (neuron) was mis-modeled as an append-only
SPEC and accreted to 63 rules. FIX: revert to a directly-edited GUIDE
(docs/guides/orchestrator-launch.md, loaded via get_guide).

This proves the revert is complete and SCOPED:
  * the EnsureOrchestrator tool + _ORCHESTRATOR_ID + _ORCHESTRATOR_SEED_ENTRIES
    are gone (module symbols + registered tool name);
  * the LEGIT cold-start floors + a2's protected-spec subsystem are UNTOUCHED —
    ensure_universal, seed_comprehension_specialists, _ensure_protected still
    exist and still guard spec-universal (the load-bearing protected contract);
  * docs/guides/orchestrator-launch.md loads via get_guide.
"""

from pathlib import Path

from edp_contracts import ToolOk

from edp_claude.server import make_context
from edp_claude.tools import build_registry
from edp_claude.tools import _tools as tools_mod

_GUIDES = Path(__file__).resolve().parents[1] / "docs" / "guides"


def _ok(res):
    assert isinstance(res, ToolOk), res
    return res.data


def _registry_names(tmp_path):
    return {t.name for t in build_registry(make_context(tmp_path))}


# ── the orchestrator spec-ness is RETIRED ────────────────────────────────────

def test_ensure_orchestrator_tool_is_gone(tmp_path):
    assert "ensure_orchestrator" not in _registry_names(tmp_path)


def test_orchestrator_module_symbols_removed():
    # the tool class + its seed constants no longer exist in the module
    assert not hasattr(tools_mod, "EnsureOrchestrator")
    assert not hasattr(tools_mod, "_ORCHESTRATOR_ID")
    assert not hasattr(tools_mod, "_ORCHESTRATOR_SEED_ENTRIES")


def test_orchestrator_definitions_are_absent():
    # no residual DEFINITIONS in the tools source (a retirement comment may
    # still NAME the old symbols — we assert the code that resurrects the
    # append-only mis-model is gone, not that the names are never mentioned)
    src = Path(tools_mod.__file__).read_text(encoding="utf-8")
    assert "class EnsureOrchestrator" not in src
    assert "_ORCHESTRATOR_SEED_ENTRIES:" not in src   # the list annotation
    assert "_ORCHESTRATOR_ID =" not in src             # the id assignment
    assert 'name = "ensure_orchestrator"' not in src   # the tool-name decl


# ── the LEGIT floors + a2 protected subsystem are PRESERVED ──────────────────

def test_legit_floors_and_protected_subsystem_preserved(tmp_path):
    names = _registry_names(tmp_path)
    # the universal coding-standards floor + comprehension seeding stay
    assert "ensure_universal" in names
    assert "seed_comprehension_specialists" in names
    # a2's protected-spec subsystem (the guard helper) is intact
    assert hasattr(tools_mod, "_ensure_protected")
    assert hasattr(tools_mod, "EnsureUniversal")
    assert hasattr(tools_mod, "SeedComprehensionSpecialists")


async def test_ensure_universal_still_guards_spec_universal(env):
    # the protected-spec subsystem still serves the legit spec-universal:
    # cold-start seeds it protected (a2's guard, unchanged by the revert)
    out = _ok(await env.call("ensure_universal"))
    assert out["spec_id"] == "spec-universal"
    spec = env.ctx.specs.load("spec-universal")
    assert spec.protected is True


# ── the orchestrator launch contract is now a GUIDE ──────────────────────────

def test_orchestrator_launch_guide_file_exists():
    assert (_GUIDES / "orchestrator-launch.md").exists()


async def test_orchestrator_launch_guide_loads_via_get_guide(env):
    out = _ok(await env.call("get_guide", name="orchestrator-launch"))
    assert out["name"] == "orchestrator-launch"
    body = out["content"].lower()
    assert body.strip(), "the guide must have loadable content"
    # it is about orchestration launch, not a spec seed
    assert "orchestrator" in body
