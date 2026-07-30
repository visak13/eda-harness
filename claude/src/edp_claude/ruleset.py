"""Assemble a worker's effective ruleset from layered specializations.

SPECIALIZATION-LAYERED-RULESETS.md (2026-06-01), Stage 3 / Decision 3.

A worker's behavior is an additive composition of layers:

    universal  →  tech extends-chain  →  per-action concern chains

resolved **universal-first, most-specific-last** (the blueprint's fixed
emit order). A later layer may ADD but never DELETE/REDEFINE an earlier
one — and that is structural, not policed here: every layer is a separate
spec file, so a tech spec literally cannot edit `spec-universal`'s entries.

The assembled ruleset is split into two VIEWS for the two roles
(Decision 1): the CONSTRUCTIVE view (how to build — for the coder, who
stays free to think) and the ENFORCED view (what to check — for the
verify reviewer, carrying adherence). MCP bindings are also surfaced
separately so the coder can prefer a deterministic snippet fetch.

This module is pure: it takes a `load(spec_id) -> Specialization | None`
callable so it is trivially testable without store/tool plumbing.
"""

from collections.abc import Callable

from pydantic import BaseModel

from .schemas import Specialization

# concern name -> spec_id convention (Decision 4): a concern "security"
# is filled by exactly one spec, `spec-security`. Predictable, no registry.
CONCERN_SPEC_PREFIX = "spec-"


class AssembleError(Exception):
    """A layering could not be resolved (cycle or missing parent). Carries
    an instruction-shaped message the tool surfaces verbatim — never a
    crash, never a silent partial assembly (blueprint §3.1)."""

    def __init__(self, instruction: str):
        super().__init__(instruction)
        self.instruction = instruction


class RulesetEntry(BaseModel):
    kind: str
    text: str
    note: str
    adherence: str
    link_role: str | None
    layer: str          # the spec_id this entry came from (provenance)


class AssembledRuleset(BaseModel):
    leaf_spec_id: str
    concerns: list[str]
    layers: list[str]                  # ordered: universal-first … leaf … concerns
    constructive: list[RulesetEntry]   # HOW to build — the coder's view
    enforced: list[RulesetEntry]       # WHAT to check — the verify view (adherence)
    mcp_bindings: list[RulesetEntry]   # link_role == "mcp_binding" (prefer-fetch)
    # s17 a7 — CONTENT-delivery guard (#18 class-b): the assembled ruleset is
    # applied in full by the worker/reviewer, so it is NOT windowed/truncated;
    # the tool wrapper stamps a non-truncating {approx_tokens, oversize} signal
    # (default None/False when constructed directly) so a ballooned composition
    # is caught in review. Optional with defaults → backward-compatible.
    approx_tokens: int | None = None
    oversize: bool = False


def _resolve_layers(
    load: Callable[[str], Specialization | None],
    leaf_spec_id: str,
    concerns: list[str],
) -> list[Specialization]:
    """Post-order DFS over `extends`, deduped, so the result is
    universal-first / most-specific-last. Concern chains are appended after
    the tech chain. Cycles and missing parents raise AssembleError."""
    ordered: list[Specialization] = []
    placed: set[str] = set()

    def walk(spec_id: str, path: frozenset[str]) -> None:
        if spec_id in path:
            chain = " -> ".join([*path, spec_id])
            raise AssembleError(
                f"extends cycle detected ({chain}); a spec cannot extend "
                f"itself transitively. Fix the `extends` of one of these specs."
            )
        spec = load(spec_id)
        if spec is None:
            raise AssembleError(
                f"layer {spec_id!r} does not exist. It is referenced via "
                f"`extends` (or as a concern). Create it (e.g. "
                f"ensure_universal for spec-universal, or train the "
                f"specialist), or drop the reference — do NOT proceed with a "
                f"partial ruleset."
            )
        for parent in spec.extends:
            walk(parent, path | {spec_id})
        if spec_id not in placed:
            placed.add(spec_id)
            ordered.append(spec)

    walk(leaf_spec_id, frozenset())
    for concern in concerns:
        walk(f"{CONCERN_SPEC_PREFIX}{concern}", frozenset())
    return ordered


def assemble_ruleset(
    load: Callable[[str], Specialization | None],
    leaf_spec_id: str,
    concerns: list[str] | None = None,
) -> AssembledRuleset:
    """Resolve + split the layered ruleset. `load` maps a spec_id to its
    Specialization (or None if absent). Raises AssembleError on an
    unresolvable layering (the caller surfaces it as an instruction-shaped
    envelope)."""
    concerns = concerns or []
    layers = _resolve_layers(load, leaf_spec_id, concerns)

    constructive: list[RulesetEntry] = []
    enforced: list[RulesetEntry] = []
    mcp_bindings: list[RulesetEntry] = []
    # Additive UNION across layers: dedupe identical (kind, text) keeping the
    # FIRST (most-universal) occurrence, so a leaf that restates a CORE rule
    # doesn't double it. Provenance (`layer`) is the earliest layer.
    seen: set[tuple[str, str]] = set()

    for spec in layers:
        for e in spec.entries:
            key = (e.kind, e.text)
            if key in seen:
                continue
            seen.add(key)
            re = RulesetEntry(
                kind=e.kind, text=e.text, note=e.note,
                adherence=e.adherence, link_role=e.link_role,
                layer=spec.spec_id,
            )
            if e.link_role == "mcp_binding":
                mcp_bindings.append(re)
                constructive.append(re)   # the coder fetches via it
            elif e.kind == "checklist" or e.link_role in ("ruleset", "checklist"):
                enforced.append(re)       # the verify worker checks it
            else:
                constructive.append(re)   # step / work_order / guideline / etc.

    return AssembledRuleset(
        leaf_spec_id=leaf_spec_id,
        concerns=concerns,
        layers=[s.spec_id for s in layers],
        constructive=constructive,
        enforced=enforced,
        mcp_bindings=mcp_bindings,
    )
