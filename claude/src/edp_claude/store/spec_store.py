"""specialization_recipe store — versioned JSON + snapshots + worklog.

Mirrors PlanStore exactly (decision: same frictionless intent-tool +
versioned-json pattern). Every save snapshots a version → the snapshots
dir IS the rollback anchor for the flow-back base (decision #2).
"""

import json
import re as _re
import uuid
from pathlib import Path

from ..schemas import Specialization, SpecEntry
from .atomic import append_jsonl, write_atomic, write_snapshot
from .attribution import actor
from .ipc_lock import StoreConflict, object_lock

# W3 (DESIGN-v6) — the amendment tag vocabulary the read-path overlay renders,
# and its bidirectional map to the SpecEntry `adherence` weight. A structured
# learning carries a bracketed `tag`; a legacy free-text learning carries an
# `adherence` word instead — the maps let either shape render + fold uniformly.
# `preferred` <-> `[hint]` (the softest weight is spelled `hint` in an overlay).
_TAG_BY_ADHERENCE = {
    "required": "[required]", "expected": "[expected]", "preferred": "[hint]",
}
_ADHERENCE_BY_TAG = {
    "[required]": "required", "[expected]": "expected", "[hint]": "preferred",
}


def _tag_for(adherence: str | None) -> str:
    return _TAG_BY_ADHERENCE.get(adherence or "expected", "[expected]")


def _adherence_for(tag: str | None) -> str:
    return _ADHERENCE_BY_TAG.get(tag or "[expected]", "expected")


def _norm_text(text: str | None) -> str:
    """Whitespace/case-folded form for the F41#5 content-checked drain —
    tolerant of reflowed lines, never of a missing rule."""
    return " ".join((text or "").split()).casefold()


_BULLET_RX = _re.compile(r"^\s*(?:[-*+]|\d+[.)]|>)\s+")


def _doc_units(content: str) -> list[str]:
    """Split a compiled doc into LOGICAL UNITS for the F42#9 anchored drain:
    each bullet/numbered/quoted item (with its indented wrap lines) or bare
    line is one unit. A rule folds only when a whole unit EQUALS it — a
    substring match let 'Superseded rule: <rule text>; now do the opposite'
    drain the very rule it contradicted."""
    units: list[str] = []
    for raw in content.splitlines():
        if not raw.strip():
            continue
        if _BULLET_RX.match(raw) or not raw[:1].isspace() or not units:
            units.append(_BULLET_RX.sub("", raw, count=1))
        else:                       # indented continuation of the last unit
            units[-1] += " " + raw.strip()
    return units


def _amendment_view(rec: dict) -> tuple[str, str, str | None]:
    """Normalise a learning record — new structured OR legacy free-text — to
    the ``(tag, rule_text, overrides)`` the overlay renders and the accept path
    folds. Migration (DESIGN-v6 §W3): a legacy record has no ``rule_text`` /
    ``tag`` — render ``rule_text`` from its ``text`` summary and derive the tag
    from its ``adherence``."""
    rule_text = rec.get("rule_text") or rec.get("text", "")
    tag = rec.get("tag") or _tag_for(rec.get("adherence"))
    return tag, rule_text, rec.get("overrides")

# W15 (DESIGN-v6): the growth budget for a PROTECTED spec. A protected spec
# is a load-bearing distilled contract, not an accreting ledger — an add
# beyond this cap is refused (`consolidate first`) at WRITE time (d24), so
# the contract stays bounded regardless of how many amendments are attempted.
PROTECTED_ENTRY_CAP = 25


class ProtectedSpecError(Exception):
    """A guarded write to a PROTECTED spec was refused: either it lacked the
    explicit `unlock`, or the spec is already at its growth budget. The
    spec-write tool translates this into a user-facing `_precondition`."""


class SpecStore:
    def __init__(self, root: Path):
        self.root = Path(root)

    def _file(self, spec_id: str) -> Path:
        return self.root / f"{spec_id}.json"

    def _dir(self, spec_id: str) -> Path:
        return self.root / spec_id

    def exists(self, spec_id: str) -> bool:
        return self._file(spec_id).exists()

    def load(self, spec_id: str) -> Specialization:
        data = json.loads(self._file(spec_id).read_text(encoding="utf-8"))
        return Specialization.model_validate(data)

    def save(self, spec: Specialization) -> int:
        # F41#1 — same locked optimistic-version discipline as
        # PlanStore.save / RecipeStore.save (F34 R2 #1): concurrent shells
        # saving the same spec must conflict loudly, never last-writer-wins
        # (two amenders both saving v9 silently erased one's entry AND its
        # snapshot).
        sdir = self._dir(spec.spec_id)
        with object_lock(sdir):
            f = self._file(spec.spec_id)
            if f.exists():
                try:
                    disk_v = json.loads(
                        f.read_text(encoding="utf-8")).get("version", 1)
                except (OSError, json.JSONDecodeError):
                    disk_v = spec.version
                if spec.version == 1 and disk_v != 1:
                    spec.version = disk_v        # fresh-object overwrite
                elif spec.version != disk_v:
                    raise StoreConflict(
                        f"spec {spec.spec_id!r} changed on disk (disk "
                        f"v{disk_v}, yours v{spec.version}) — another shell "
                        "saved after your load. Nothing was written; "
                        "re-read the spec and re-apply your change.")
            spec.version += 1
            payload = spec.model_dump(mode="json")
            write_atomic(f, json.dumps(payload, indent=2))
            write_snapshot(sdir / "snapshots", spec.version, payload)
            append_jsonl(
                sdir / "worklog.jsonl",
                # W15: stamp actor attribution (by:{role,handle}) resolved
                # IN CODE from the environment (attribution.actor(),
                # principle-6) so every spec_saved record carries who
                # performed the write.
                {"kind": "spec_saved", "version": spec.version,
                 "entries": len(spec.entries), "by": actor()},
            )
            return spec.version

    def add_entry(
        self, spec_id: str, entry: SpecEntry, *, unlock: bool = False
    ) -> int:
        """Append one entry to a spec, ENFORCING the protected-write policy
        (W15). For a protected spec the write is refused unless `unlock` is
        set (and it is always actor-attributed via save()), and it is refused
        once the spec is at its growth budget (PROTECTED_ENTRY_CAP) — the cap
        is checked at WRITE time (d24). An ordinary (unprotected) spec is
        unguarded and uncapped. Returns the new version. Raises
        ProtectedSpecError on refusal (the tool maps it to a precondition)."""
        # F41#1 — the whole read-modify-write runs under the object lock
        # (reentrant with save()'s), so a concurrent amender conflicts on
        # the version check instead of racing the load.
        with object_lock(self._dir(spec_id)):
            spec = self.load(spec_id)
            if spec.protected:
                if not unlock:
                    raise ProtectedSpecError(
                        f"{spec_id!r} is a protected spec — pass unlock=true "
                        f"to amend it (the write is actor-attributed)."
                    )
                if len(spec.entries) >= PROTECTED_ENTRY_CAP:
                    raise ProtectedSpecError(
                        f"{spec_id!r} is at its growth budget of "
                        f"{PROTECTED_ENTRY_CAP} entries — consolidate first "
                        f"before adding more."
                    )
            spec.entries.append(entry)
            return self.save(spec)

    def append_worklog(self, spec_id: str, record: dict) -> None:
        append_jsonl(self._dir(spec_id) / "worklog.jsonl", record)

    # ── compiled doc (SPECIALIST-COMPILED-DOCS.md, 2026-06-02) ──────────────
    # The worker-facing artifact: a self-contained, per-stack instruction doc
    # the SME compiles at end of (re)training. Lives next to the JSON +
    # snapshots so all of a spec's artifacts are together + diffable.
    def doc_path(self, spec_id: str) -> Path:
        return self._dir(spec_id) / "compiled.md"

    def write_doc(self, spec_id: str, content: str) -> Path:
        path = self.doc_path(spec_id)
        write_atomic(path, content)
        append_jsonl(self._dir(spec_id) / "worklog.jsonl",
                     {"kind": "doc_compiled", "bytes": len(content)})
        # F34 R2 #10 (2026-08-18): a recompile DRAINS the overlay. The
        # design always said "a post-recompile marker supersedes and
        # drains the learning" — but nothing ever wrote that marker, so
        # every promoted learning stayed overlaid forever: workers read
        # the rule once in the recompiled base and again as an amendment,
        # and an `overrides` match could stamp the NEW base text
        # SUPERSEDED. The SME recompiles against the promoted set by
        # contract (specialist card step 4), so compiling IS the fold.
        #
        # F41#5: the drain is CONTENT-CHECKED, not blind — a non-empty doc
        # that omitted an accepted rule used to drain it anyway, so the
        # rule vanished from both the base AND the overlay. A learning is
        # drained only when its rule text demonstrably appears in the
        # submitted doc (whitespace/case-folded substring); an unmatched
        # learning STAYS overlaid (fail-safe: worst case is a duplicate
        # delivery, never a lost accepted rule) and is named in the
        # worklog so the SME can fold or reword it.
        # F42#9 — ANCHORED, not substring: the rule must BE a whole unit
        # (bullet/line, wraps folded) of the doc, so a mention inside a
        # negating or "superseded" sentence can never drain the rule.
        doc_units = {_norm_text(u) for u in _doc_units(content)}
        kept: list[str] = []
        for rec in self.accepted_pending_learnings(spec_id):
            _, rule_text, _ = _amendment_view(rec)
            if _norm_text(rule_text) and _norm_text(rule_text) in doc_units:
                marker = dict(rec)
                marker["status"] = "compiled"
                self.append_learning(spec_id, marker)
            else:
                kept.append(rec.get("learning_id") or "?")
        if kept:
            append_jsonl(self._dir(spec_id) / "worklog.jsonl",
                         {"kind": "doc_compile_kept_overlay",
                          "learning_ids": kept,
                          "detail": "accepted rules NOT found in the "
                                    "compiled doc — overlay retained"})
        return path

    def read_doc(self, spec_id: str, *, with_overlay: bool = False) -> str | None:
        """Read a spec's compiled worker-facing doc.

        Default (``with_overlay=False``) is UNCHANGED — return ``compiled.md``
        verbatim, or None when no doc has been compiled.

        ``with_overlay=True`` (W3 read-path overlay, DESIGN-v6 §W3): compose the
        compiled doc with a generated ``## Field amendments (accepted, pending
        recompile)`` section rendered from `accepted_pending_learnings`, so an
        accepted learning is LIVE to every worker/reviewer read immediately —
        before the periodic full SME recompile folds it into ``compiled.md``.
        Each amendment is tagged; the section header declares **amendments
        override any contradicting rule above**. A learning carrying an
        ``overrides`` fragment annotates the matched base fragment IN PLACE with
        a ``> SUPERSEDED by amendment Ln:`` prefix (substring match; an
        unmatched fragment still lists its amendment). No compiled doc → None
        even with the overlay (nothing to overlay onto); no accepted-pending
        learnings → the base doc unchanged (no empty section)."""
        path = self.doc_path(spec_id)
        if not path.exists():
            return None
        base = path.read_text(encoding="utf-8")
        if not with_overlay:
            return base
        pending = self.accepted_pending_learnings(spec_id)
        if not pending:
            return base
        lines: list[str] = []
        for n, rec in enumerate(pending, start=1):
            tag, rule_text, overrides = _amendment_view(rec)
            if overrides and overrides in base:
                base = base.replace(
                    overrides, f"> SUPERSEDED by amendment L{n}: {overrides}", 1
                )
            lines.append(f"- L{n} {tag} {rule_text}")
        section = (
            "\n\n## Field amendments (accepted, pending recompile)\n\n"
            "**amendments override any contradicting rule above**\n\n"
            + "\n".join(lines)
            + "\n"
        )
        return base + section

    def has_doc(self, spec_id: str) -> bool:
        return self.doc_path(spec_id).exists()

    # ── quarantined learning proposals (SPEC-FLOWBACK, 2026-06-04) ──────────
    # The flow-back sidecar: stack-craft a worker discovered in the field,
    # PROPOSED back to the spec but NOT yet part of it. Lives next to the
    # JSON/snapshots/compiled doc, but is DELIBERATELY a separate file the
    # live read path (load / assemble_ruleset / read_doc) never touches — a
    # proposal must clear the existing update_specialist→recompile→USER gate
    # before any of its content can reach a worker. Append-only; status is
    # carried per-record so triage is a pull-only read at existing
    # checkpoints (no daemon, no watchdog).
    def learnings_path(self, spec_id: str) -> Path:
        return self._dir(spec_id) / "learnings.jsonl"

    def append_learning(self, spec_id: str, record: dict) -> None:
        append_jsonl(self.learnings_path(spec_id), record)

    def read_learnings(
        self, spec_id: str, status: str | None = None
    ) -> list[dict]:
        path = self.learnings_path(spec_id)
        if not path.exists():
            return []
        # Last-write-wins per learning_id: an append-only RESOLUTION record
        # (status 'promoted'/'rejected', via resolve_spec_learning) supersedes
        # the earlier 'proposed' one, so a resolved learning leaves the
        # 'proposed' queue while the file stays append-only (crash-safe).
        latest: dict = {}
        order: list = []
        loose: list[dict] = []
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:  # F34 R2 #11 — a torn line never poisons the overlay read
                rec = json.loads(line)
            except json.JSONDecodeError:
                continue
            lid = rec.get("learning_id")
            if lid is None:
                loose.append(rec)
                continue
            if lid not in latest:
                order.append(lid)
            latest[lid] = rec
        merged = [latest[lid] for lid in order] + loose
        if status is None:
            return merged
        return [r for r in merged if r.get("status") == status]

    # ── W3 automated spec flowback (DESIGN-v6 §W3) ──────────────────────────
    # Four store-side primitives the a2 _tools.py wiring calls: the structured
    # auto-propose write, the accepted-pending query the overlay renders, the
    # read-path overlay itself (read_doc above), and the batch accept-side
    # fold-into-entries. The sidecar file + last-write-wins parse (above) are
    # unchanged — these only ADD the structured shape + the accept semantics.
    def append_proposed_learning(
        self,
        spec_id: str,
        *,
        rule_text: str,
        tag: str = "[expected]",
        overrides: str | None = None,
        source: dict | None = None,
        learning_id: str | None = None,
    ) -> str:
        """Append a STRUCTURED W3 ``proposed`` learning to the quarantined
        sidecar and return its ``learning_id``. Record shape (DESIGN-v6 §W3):
        ``{"learning_id","rule_text","tag","overrides","source":{"recipe_id",
        "action_id"},"status":"proposed"}``. ``source`` is stored as-is (a
        {recipe_id, action_id} dict) or null.

        THE ONLY WRITER is the auto-propose branch of ``emit_recipe_event(
        kind="learning")``. The explicit ``propose_spec_learning`` verb this
        docstring used to name was RETIRED from every role surface by W6.4 —
        no role can call it. Legacy free-text proposals remain readable
        (``read_learnings`` parses both shapes).

        NOTE THE CAPABILITY BOUND, because the shape is the reason for it: this
        record carries **no ``kind``**, and ``resolve_spec_learnings`` has no
        parameter to set one — so an accepted learning CANNOT be typed as an
        anti-pattern at either end and flattens to a neutral ``checklist`` entry.
        What survives is the PROHIBITION ITSELF (a "NEVER do X" rule lands
        verbatim in ``rule_text``) and adherence (as ``tag``). Lost is the
        STRUCTURED TYPING, not the rule. Restoring it means amending the W3
        record shape in DESIGN-v6 — a design change, not a local fix."""
        lid = learning_id or f"learn-{uuid.uuid4().hex[:12]}"
        self.append_learning(spec_id, {
            "learning_id": lid,
            "rule_text": rule_text,
            "tag": tag,
            "overrides": overrides,
            "source": dict(source) if source else None,
            "status": "proposed",
        })
        return lid

    def accepted_pending_learnings(self, spec_id: str) -> list[dict]:
        """The accepted-but-not-yet-recompiled learnings a `read_doc` overlay
        renders (DESIGN-v6 §W3). 'Accepted' == latest status ``promoted``
        (`resolve_spec_learnings` writes that word AND carries rule_text / tag /
        overrides forward, so each record here is self-contained). Because
        `read_learnings` is last-write-wins, a later record with a different
        status (e.g. a post-recompile marker) supersedes and drains the learning
        from this set — that is how a full SME recompile clears the overlay."""
        return self.read_learnings(spec_id, status="promoted")

    def resolve_spec_learnings(
        self,
        spec_id: str,
        *,
        accept: list[str] | None = None,
        reject: list[str] | None = None,
        note: str = "",
    ) -> dict:
        """Batch-resolve proposed learnings (DESIGN-v6 §W3 — the single cheap
        human gate). A GENUINE semantic change over the per-item
        `resolve_spec_learning` (which only marked promoted/rejected and left
        the entry-append + recompile to a human):

        - REJECT ids → append a ``{status:'rejected'}`` resolution record
          (drains the proposed queue via last-write-wins). No spec mutation.
        - ACCEPT ids → append a ``{status:'promoted', rule_text, tag, overrides,
          source, note}`` record CARRYING the learning's content forward (so the
          overlay + accepted-pending query stay self-contained), AND append the
          rule to ``spec.entries``, then bump the version ONCE via `save`.

        Migration: a legacy proposed record (``text``/``kind``/``adherence``,
        no ``rule_text``) is normalised on accept — rule_text=<its text
        summary>, tag derived from adherence, entry ``kind`` reused (else a
        neutral ``checklist`` default). Unknown or empty-text ids are skipped
        (the a2 tool verb validates membership up front). Returns
        ``{"spec_id","accepted":[...],"rejected":[...],"version":<int>}`` —
        ``version`` is bumped only if anything was accepted."""
        accept = list(accept or [])
        reject = list(reject or [])

        # F41#1 — accept-side entry-append + save is a read-modify-write:
        # run it under the object lock so a concurrent amender conflicts
        # loudly instead of one promotion erasing the other.
        # F42#8 — the learning states are ALSO read under that lock, and
        # only a record whose LATEST status is 'proposed' transitions: a
        # retry or a concurrent duplicate accept of an already-resolved id
        # is an idempotent no-op, never a second appended rule.
        with object_lock(self._dir(spec_id)):
            by_id = {
                r.get("learning_id"): r
                for r in self.read_learnings(spec_id)
                if r.get("learning_id") is not None
            }

            rejected: list[str] = []
            for lid in reject:
                rec = by_id.get(lid)
                if rec is not None and rec.get("status") != "proposed":
                    continue            # already resolved — idempotent no-op
                self.append_learning(spec_id, {
                    "learning_id": lid, "status": "rejected", "note": note,
                })
                rejected.append(lid)

            spec = self.load(spec_id)
            accepted: list[str] = []
            for lid in accept:
                rec = by_id.get(lid)
                if rec is None or rec.get("status") != "proposed":
                    continue            # unknown or already resolved
                tag, rule_text, overrides = _amendment_view(rec)
                if not rule_text.strip():
                    continue
                self.append_learning(spec_id, {
                    "learning_id": lid,
                    "status": "promoted",
                    "rule_text": rule_text,
                    "tag": tag,
                    "overrides": overrides,
                    "source": rec.get("source"),
                    "note": note,
                })
                spec.entries.append(SpecEntry(
                    kind=rec.get("kind") or "checklist",
                    text=rule_text,
                    adherence=_adherence_for(tag),
                ))
                accepted.append(lid)

            version = self.save(spec) if accepted else spec.version
        return {
            "spec_id": spec_id,
            "accepted": accepted,
            "rejected": rejected,
            "version": version,
        }
