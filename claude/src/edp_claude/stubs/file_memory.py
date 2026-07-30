"""File-backed memory (LLD §3; DESIGN-v4 §5 — KG deferred, text file may
suffice). recall/remember over lineage-scoped facts.jsonl trails.

DESIGN-v6 W4/a4 — facts are stored per LINEAGE SCOPE under .memory/:
  .memory/global/facts.jsonl            (visible everywhere; neuron-only write)
  .memory/recipe/<recipe_id>/facts.jsonl (visible in-recipe only)
  .memory/domain/<domain>/facts.jsonl    (visible to that domain)
recall FANS OUT across global + the caller's recipe + domain scopes and
merges, so a recipe-scoped fact surfaces in its own recipe but NOT in
another recipe's recall unless it was written global. LAZY legacy
fallback: when NO scoped file exists yet, recall still reads the pre-v6
flat .memory/facts.jsonl (hydrate-on-read; never a batch migration).

The scope DECISION (default-from-lineage, global-neuron-only guard,
domain-from-recipe) is made in the tool layer (_tools.py) which has ctx +
env; this port receives an already-resolved scope + key and just picks
the file. All writes go through store/atomic.py's append_jsonl chokepoint.

# TODO(edp-memory-svc): if a flat file proves insufficient over time,
# swap MemoryPort to an HTTP KG facade behind the SAME interface.
"""

import json
from pathlib import Path

from edp_contracts import Tool
from pydantic import BaseModel

from ..domains import kg_filter_for
from ..ports import MemoryPort, ToolResult
from ..store.atomic import append_jsonl, read_jsonl


class _Remembered(BaseModel):
    stored: bool
    reason: str
    scope: str | None = None


class FileMemory(MemoryPort):
    def __init__(self, facts_path: Path):
        # `facts_path` stays the pre-v6 flat trail (.memory/facts.jsonl) for
        # legacy fallback; its parent is the .memory root under which the
        # scoped trails live.
        self.path = Path(facts_path)
        self.root = self.path.parent

    # ── scope → file resolution ──────────────────────────────────────────
    def _scope_path(
        self, scope: str, recipe_id: str | None, domain: str | None,
    ) -> Path | None:
        """Map a resolved (scope, key) to its facts.jsonl. Returns None when
        the scope needs a key that is missing (caller/tool layer guards this
        first, so this is a defensive fallback)."""
        if scope == "global":
            return self.root / "global" / "facts.jsonl"
        if scope == "recipe" and recipe_id:
            return self.root / "recipe" / recipe_id / "facts.jsonl"
        if scope == "domain" and domain:
            return self.root / "domain" / domain / "facts.jsonl"
        return None

    def _candidate_paths(
        self, recipe_id: str | None, domain: str | None,
    ) -> list[Path]:
        """The scoped trails a recall fans out over: global always, plus the
        caller's recipe + domain when derivable."""
        paths = [self.root / "global" / "facts.jsonl"]
        if recipe_id:
            paths.append(self.root / "recipe" / recipe_id / "facts.jsonl")
        if domain:
            paths.append(self.root / "domain" / domain / "facts.jsonl")
        return paths

    async def recall(
        self,
        query: str,
        scope: str | None = None,
        *,
        recipe_id: str | None = None,
        domain: str | None = None,
    ) -> list[dict]:
        paths = self._candidate_paths(recipe_id, domain)
        # LAZY legacy fallback: only when NO scoped trail exists yet do we
        # read the pre-v6 flat location (hydrate-on-read, no migration).
        if not any(p.exists() for p in paths):
            paths.append(self.path)
        q = query.lower()
        out: list[dict] = []
        seen: set[str] = set()
        for p in paths:
            for rec in read_jsonl(p):
                text = json.dumps(rec, default=str).lower()
                if not all(tok in text for tok in q.split()):
                    continue
                key = json.dumps(rec, sort_keys=True, default=str)
                if key in seen:
                    continue
                seen.add(key)
                out.append(rec)
        return out

    async def remember(
        self,
        fact: dict,
        domain: str | None,
        *,
        scope: str = "recipe",
        recipe_id: str | None = None,
    ) -> ToolResult:
        verdict = kg_filter_for(domain)(fact)
        if not verdict.keep:
            return Tool.ok(_Remembered(stored=False, reason=verdict.reason,
                                       scope=scope))
        target = self._scope_path(scope, recipe_id, domain)
        if target is None:
            # Should be prevented by the tool-layer guard; surface plainly
            # rather than silently mis-filing the fact.
            return Tool.ok(_Remembered(
                stored=False,
                reason=(f"scope {scope!r} could not resolve a target trail "
                        "(missing recipe_id/domain key)"),
                scope=scope))
        record = {**fact, "domain": domain, "scope": scope}
        if recipe_id:
            record["recipe_id"] = recipe_id
        append_jsonl(target, record)
        return Tool.ok(_Remembered(stored=True, reason=verdict.reason,
                                   scope=scope))
