"""Specialization neuron schemas (vision 2026-05-22, phases 2+3).

Two objects:
  - NeuronRecord  — a row in the unified neuron DB (decision #1: domain
    experts, comprehension checkers, AND orchestration all live here).
    The discovery embedding is an INDEX artifact (a BLOB column in
    NeuronStore), never part of this public record.
  - Specialization — the versioned `specialization_recipe`: a rough
    step-wise doc + knowledge LINKS (decision: links, not an embedded
    content store) + the memory layer (anti-patterns, checklists,
    work-order, preferences) a specialist reaches via next_action.
    Versioned so it is the rollback anchor for the flow-back base
    (decision #2).
"""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_serializer

# Lifecycle: trained → pending_review → stable → underused → archived
# (decision #3 adds the pending_review HITL gate). Only `stable` neurons
# are branchable for real work.
NeuronStatus = Literal[
    "trained", "pending_review", "stable", "underused", "archived"
]
NeuronCategory = Literal["comprehension", "domain", "orchestration"]


class NeuronRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")

    neuron_id: str = Field(min_length=1)
    name: str = Field(min_length=1)
    description: str = Field(min_length=1)  # embedded for neuron_search
    category: NeuronCategory = "domain"
    status: NeuronStatus = "pending_review"
    # The branchable snapshot pointer: the trained base shell's
    # session_id. `claude --resume <base> --fork-session` branches it.
    # null until the specialist has actually been trained into a shell.
    base_session_id: str | None = None
    spec_id: str | None = None          # → Specialization (recipe)
    editable: bool = True               # shipped seeds set False
    use_count: int = 0
    flag_count: int = 0                 # feedback-decay signal (decision #4)
    created_at: datetime
    updated_at: datetime
    trained_at: datetime | None = None  # TTL-decay anchor (decision #4)
    last_used_at: datetime | None = None


SpecEntryKind = Literal[
    "step", "link", "checklist", "anti_pattern", "preference", "work_order"
]

# SPECIALIZATION-LAYERED-RULESETS.md (2026-06-01), Decision 2.
# Adherence is defined by what the VERIFY worker does — vague modality
# (must/should) gets discarded by the LLM, so each level names a concrete
# verify behavior (the spec/reviewer brief defines them):
#   required  → blocks `done`; verify fixes the gap or fails the action.
#   expected  → verify checks + fixes if clear; a justified, recorded
#               exception is allowed; does NOT hard-block.
#   preferred → the coder's house-style default; verify only notes a
#               deviation, never blocks.
# Default `expected` so pre-2026-06-01 flat entries keep their weight.
SpecAdherence = Literal["required", "expected", "preferred"]

# Role-typing for `kind="link"` (and other entries) — a bare link was
# undifferentiated. `null` = untyped (legacy / not a link).
#   ruleset     → a doc whose rules the verify worker enforces
#   checklist   → a doc of things to verify
#   guideline   → design guidance for the coder (constructive)
#   reference   → may-skim background, not enforced
#   mcp_binding → "prefer this globally-available MCP server for subtask X"
SpecLinkRole = Literal[
    "ruleset", "checklist", "guideline", "reference", "mcp_binding"
]


class SpecEntry(BaseModel):
    model_config = ConfigDict(extra="forbid")
    kind: SpecEntryKind
    # for kind="link" this is the URL / doc path (knowledge-as-links);
    # for everything else it is the line of guidance.
    text: str = Field(min_length=1)
    note: str = ""
    # 2026-06-01 (additive): adherence strength + link role. Defaults keep
    # every pre-existing entry valid and equally-weighted (`expected`).
    adherence: SpecAdherence = "expected"
    link_role: SpecLinkRole | None = None


class Specialization(BaseModel):
    model_config = ConfigDict(extra="forbid")

    spec_id: str = Field(min_length=1)
    neuron_id: str = Field(min_length=1)
    name: str = Field(min_length=1)
    subject: str = Field(min_length=1)   # "Java / DDD / Spring Boot"
    entries: list[SpecEntry] = Field(default_factory=list)
    # 2026-06-01 (additive) — static layering (Decision 3a). The spec_ids
    # this spec composes on top of, resolved universal-first /
    # most-specific-last and ADDITIVELY (a later layer may add but never
    # delete/redefine a CORE entry). Default `["spec-universal"]` so every
    # legacy spec gains the universal layer as its implicit parent.
    # `spec-universal` itself is created with `extends=[]` (no self-loop).
    extends: list[str] = Field(default_factory=lambda: ["spec-universal"])
    # W15 (DESIGN-v6, additive) — a PROTECTED spec is the load-bearing
    # contract (spec-universal): its writes are guarded
    # (require an explicit unlock + actor attribution) and its growth is
    # capped (SpecStore.PROTECTED_ENTRY_CAP) so it stays a bounded distilled
    # contract, never an unbounded ledger. Default False so an ordinary spec
    # is unaffected; emission-gated below (omitted at its default) so a legacy
    # spec — o6 — serializes byte-shape-identical on a no-op load.
    protected: bool = False
    created_at: datetime
    updated_at: datetime
    version: int = Field(ge=1, default=1)

    @model_serializer(mode="wrap")
    def _ser_protected_gate(self, handler):
        # o6: omit `protected` at its default so a legacy spec (no protected
        # key) round-trips byte-shape-identical. Only a genuinely-protected
        # spec emits the key. (Same emission-gate discipline as Decision.)
        data = handler(self)
        if not data.get("protected"):
            data.pop("protected", None)
        return data
