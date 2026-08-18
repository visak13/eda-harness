"""Tiered storage (P2, 2026-06-10) — digest inline, full text in sidecars.

WHY: recipe/plan JSON grows monotonically and the bulk is a handful of long
text fields (decision texts 1-3KB, step descriptions 1-2KB, acceptance
evidence blobs 3-6KB). Tiering moves each long text to a sidecar file and
keeps a one-line digest + a `*_ref` pointer inline, so the live JSON and
every snapshot stay small while NOTHING agent-facing changes.

THE HARD CONSTRAINT (no behavior loss): the stores are the single load/save
chokepoint — `hydrate_*` runs before `model_validate`, so the IN-MEMORY
model always carries the FULL text. Every consumer (worker grounding via
_resolve_action_injected, read_object full reads, pool_spawn_worker
stamping, recipe_context titles) reads the hydrated model and is therefore
byte-identical by construction. Only the on-disk shape changes.

ROLLOUT RULES:
- `EDP_TIER_WRITE=1` gates ADOPTION only (tiering a field that has no ref
  yet). Once a field carries a `*_ref`, saves ALWAYS re-dehydrate it —
  one-way consistency, so toggling the flag off can never leave an edited
  inline text shadowed by a stale sidecar. Re-dehydrating is not the same
  as re-WRITING: `_write_sidecar` skips the IO when the sidecar's content
  already equals the live text (s24/B1), which keeps the invariant while
  making a no-change save sidecar-IO-free.
- Legacy files (no refs) hydrate as a no-op and, with the flag off,
  re-save byte-shape-identical (the RP-A emission-gate discipline).
- A missing sidecar DEGRADES (the inline digest is served + a warning is
  attached for the trail) — it never crashes a load.
"""

import hashlib
import json
import os
from pathlib import Path

from .atomic import write_atomic


def _cas_name(base_ref: str, text: str) -> str:
    """F34 R2 #3/#4 (2026-08-18) — CONTENT-ADDRESSED sidecar names.

    Sidecars used to be overwritten IN PLACE at a name derived from the
    logical id (context/d1.md). That made every snapshot a liar: v5's
    payload referenced context/d1.md, v6 overwrote it, and 'restoring'
    v5 hydrated v6's text. It also opened a crash split-brain: sidecar
    written, process dies before recipe.json replaces — the old JSON now
    hydrates the NEW text. With content-addressing, new content gets a
    NEW file (context/d1-<sha10>.md) and the old file stays for every
    snapshot that references it; a crash leaves the old JSON pointing at
    the old, untouched bytes. Legacy plain refs remain readable and
    migrate to CAS names on the next content change."""
    h = hashlib.sha256(text.encode("utf-8")).hexdigest()[:10]
    if "." in base_ref.rsplit("/", 1)[-1]:
        stem, ext = base_ref.rsplit(".", 1)
        return f"{stem}-{h}.{ext}"
    return f"{base_ref}-{h}"

#: minimum utf-8 byte length before a text is tiered out to a sidecar.
TIER_THRESHOLD_DEFAULT = 600

#: marker prefix for tiered values inside plain dicts (Plan.injected_context
#: values), where there is no pydantic field to hang a `*_ref` on. Shape:
#: "@file:<relpath>\n<digest>" — first line is the pointer, rest the digest.
FILE_MARKER = "@file:"


def _threshold() -> int:
    try:
        return int(os.environ.get("EDP_TIER_THRESHOLD_BYTES",
                                  str(TIER_THRESHOLD_DEFAULT)))
    except ValueError:
        return TIER_THRESHOLD_DEFAULT


def tier_write_enabled() -> bool:
    return os.environ.get("EDP_TIER_WRITE", "0") == "1"


def _digest_line(text: str, ref: str, limit: int = 120) -> str:
    """One-line inline stand-in for a tiered text: first line (capped) +
    an explicit pointer so a human reading the raw JSON knows where the
    bytes went."""
    first = text.strip().splitlines()[0].strip() if text.strip() else ""
    if len(first) > limit:
        first = first[:limit].rstrip() + "…"
    n = len(text.encode("utf-8"))
    return f"{first} … [{n} bytes; full text in {ref}]"


def _read_sidecar(root: Path, ref: str) -> str | None:
    p = root / ref
    try:
        return p.read_text(encoding="utf-8")
    except (FileNotFoundError, OSError):
        return None


def _write_sidecar(root: Path, ref: str, text: str) -> bool:
    """Write a sidecar ONLY when its content would change. Returns whether the
    write happened.

    Dehydration runs on EVERY save and an already-reffed field is always
    re-dehydrated, so without this guard each save rewrote every sidecar (~370
    files for the legacy fixture). That is what made the heartbeat's save path
    non-IO-free and what put `os.replace` under contention on Windows. Tolerating
    the lock would mask the contention; not writing removes it.

    The one-way-consistency invariant (sidecar content == live text) is preserved
    by construction: the write is skipped ONLY when the on-disk bytes already
    equal `text`. A missing sidecar, an unreadable one, or differing content all
    fall through to the write, so the guard can never leave a stale sidecar
    behind. The caller's inline digest substitution is deliberately NOT gated on
    the return value — skipping it would leave full text inline and untier the
    field.
    """
    if _read_sidecar(root, ref) == text:
        return False
    write_atomic(root / ref, text)
    return True


def _dehydrate_field(obj: dict, field: str, ref_field: str, ref: str,
                     root: Path) -> None:
    """Tier one field of one dict in place. Adoption (no ref yet) requires
    the flag + threshold; an already-reffed field is ALWAYS re-dehydrated
    so sidecar and inline digest stay consistent with the live text."""
    text = obj.get(field)
    if not isinstance(text, str) or not text:
        return
    if text.startswith(FILE_MARKER):
        return  # already a marker (defensive; fields use refs, not markers)
    has_ref = bool(obj.get(ref_field))
    is_digest = obj.get(ref_field) and f"full text in {obj[ref_field]}" in text
    if is_digest:
        return  # already dehydrated (e.g. degraded load re-saved)
    if not has_ref:
        if not tier_write_enabled():
            return
        if len(text.encode("utf-8")) <= _threshold():
            return
    # F34 R2 #3/#4 — the overwrite rule:
    # - content UNCHANGED → keep the existing ref (legacy or CAS), zero IO.
    # - sidecar MISSING   → recreate at the existing ref (fail-safe; nothing
    #   is overwritten, and the payload shape stays byte-identical).
    # - content CHANGED   → publish under a NEW content-addressed name; the
    #   old file is never overwritten, so every snapshot referencing it
    #   stays truthful and a crash before the main JSON replace leaves the
    #   old object pointing at old bytes.
    cur = obj.get(ref_field)
    if cur:
        on_disk = _read_sidecar(root, cur)
        if on_disk == text or on_disk is None:
            _write_sidecar(root, cur, text)   # no-op when equal
            obj[field] = _digest_line(text, cur)
            return
    cas = _cas_name(ref, text)
    _write_sidecar(root, cas, text)
    obj[ref_field] = cas
    obj[field] = _digest_line(text, cas)


def _hydrate_field(obj: dict, field: str, ref_field: str, root: Path,
                   warnings: list[str]) -> None:
    ref = obj.get(ref_field)
    if not ref:
        return
    full = _read_sidecar(root, ref)
    if full is None:
        warnings.append(
            f"sidecar missing for {ref_field}={ref!r}; serving the inline "
            "digest (degraded — full text unavailable)")
        return
    obj[field] = full


# ── recipe payloads ─────────────────────────────────────────────────────────

def dehydrate_recipe_payload(payload: dict, recipe_dir: Path) -> dict:
    """Tier the long recipe texts: Decision.text → context/<id>.md,
    Decision.rationale → context/<id>-rationale.md, Assumption.text →
    context/assumption-<id>.md, RejectedOption.text →
    context/rejected-<id>.md, RecipeStep.description → context/step-<id>.md.
    Mutates + returns the payload (a model_dump dict the caller owns)."""
    ctx = payload.get("context") or {}
    for d in ctx.get("decisions", []):
        _dehydrate_field(d, "text", "text_ref",
                         f"context/{d.get('id', 'unknown')}.md", recipe_dir)
        _dehydrate_field(
            d, "rationale", "rationale_ref",
            f"context/{d.get('id', 'unknown')}-rationale.md", recipe_dir)
    for a in ctx.get("assumptions", []):
        _dehydrate_field(
            a, "text", "text_ref",
            f"context/assumption-{a.get('id', 'unknown')}.md", recipe_dir)
    for r in ctx.get("rejected_options", []):
        _dehydrate_field(
            r, "text", "text_ref",
            f"context/rejected-{r.get('id', 'unknown')}.md", recipe_dir)
    for s in payload.get("steps", []):
        _dehydrate_field(
            s, "description", "description_ref",
            f"context/step-{s.get('step_id', 'unknown')}.md", recipe_dir)
    return payload


def hydrate_recipe_payload(data: dict, recipe_dir: Path,
                           warnings: list[str] | None = None) -> dict:
    """Resolve recipe `*_ref` pointers back to full text BEFORE validation.
    Legacy data (no refs) passes through untouched."""
    warnings = warnings if warnings is not None else []
    ctx = data.get("context") or {}
    for d in ctx.get("decisions", []):
        _hydrate_field(d, "text", "text_ref", recipe_dir, warnings)
        _hydrate_field(d, "rationale", "rationale_ref", recipe_dir, warnings)
    for a in ctx.get("assumptions", []):
        _hydrate_field(a, "text", "text_ref", recipe_dir, warnings)
    for r in ctx.get("rejected_options", []):
        _hydrate_field(r, "text", "text_ref", recipe_dir, warnings)
    for s in data.get("steps", []):
        _hydrate_field(s, "description", "description_ref", recipe_dir,
                       warnings)
    return data


# ── plan payloads ───────────────────────────────────────────────────────────

def dehydrate_plan_payload(payload: dict, plan_dir: Path) -> dict:
    """Tier the long plan texts: Action.description → context/action-
    <action_id>.md; Acceptance.actual → evidence/<action_id>-actual.md;
    Plan.injected_context values → context/<ctx_id>.md via the in-dict
    @file: marker (dict values have no pydantic field for a ref)."""
    for a in payload.get("actions", []):
        _dehydrate_field(
            a, "description", "description_ref",
            f"context/action-{a.get('action_id', 'unknown')}.md", plan_dir)
        acc = a.get("acceptance")
        if isinstance(acc, dict):
            # EVIDENCE CLOBBER (2026-08-13 hardening run, s3 live loss):
            # this sidecar used to adopt `evidence/<action_id>-actual.md` —
            # the SAME path the fleet's evidence convention has workers
            # write their full raw transcripts to. Because an already-reffed
            # field is ALWAYS re-dehydrated, every plan save then overwrote
            # the worker's 5-8KB transcript with the ~1200-char capped
            # `actual` string (s3 a2: 7810 B → 1759 B, verbatim SSE
            # transcripts destroyed). The record's tier file now lives at
            # `-actual-record.md`; the worker's evidence path is never
            # written by the store. Legacy refs already pointing at the
            # collided path migrate on next save: the ref is re-pointed and
            # the worker's file left alone.
            aid = a.get('action_id', 'unknown')
            legacy = f"evidence/{aid}-actual.md"
            inline = acc.get("actual") or ""
            # Skip migration on a degraded load (inline text IS the old
            # digest line) — re-pointing there would tier the digest line
            # itself as the record's full text.
            if (acc.get("actual_ref") == legacy
                    and f"full text in {legacy}" not in inline):
                acc["actual_ref"] = f"evidence/{aid}-actual-record.md"
            _dehydrate_field(
                acc, "actual", "actual_ref",
                f"evidence/{aid}-actual-record.md",
                plan_dir)
    inj = payload.get("injected_context")
    if isinstance(inj, dict):
        for cid, text in list(inj.items()):
            if not isinstance(text, str) or not text:
                continue
            if text.startswith(FILE_MARKER):
                # already tiered: keep marker, but refresh nothing — the
                # hydrated load would have replaced it with full text, so a
                # marker here means this payload was never hydrated.
                continue
            ref = f"context/{cid}.md"
            already = ((plan_dir / ref).exists()
                       or bool(list(plan_dir.glob(f"context/{cid}-*.md"))))
            if not already and (not tier_write_enabled()
                                or len(text.encode("utf-8")) <= _threshold()):
                continue
            # F34 R2 #3/#4 — content-addressed name; old bytes never
            # overwritten (see _cas_name).
            cas = _cas_name(ref, text)
            _write_sidecar(plan_dir, cas, text)
            inj[cid] = f"{FILE_MARKER}{cas}\n{_digest_line(text, cas)}"
    return payload


def hydrate_plan_payload(data: dict, plan_dir: Path,
                         warnings: list[str] | None = None) -> dict:
    """Resolve plan pointers back to full text BEFORE validation."""
    warnings = warnings if warnings is not None else []
    for a in data.get("actions", []):
        _hydrate_field(a, "description", "description_ref", plan_dir, warnings)
        acc = a.get("acceptance")
        if isinstance(acc, dict):
            _hydrate_field(acc, "actual", "actual_ref", plan_dir, warnings)
    inj = data.get("injected_context")
    if isinstance(inj, dict):
        for cid, text in list(inj.items()):
            if isinstance(text, str) and text.startswith(FILE_MARKER):
                ref = text[len(FILE_MARKER):].splitlines()[0].strip()
                full = _read_sidecar(plan_dir, ref)
                if full is None:
                    warnings.append(
                        f"sidecar missing for injected_context[{cid!r}] "
                        f"({ref!r}); serving the inline digest (degraded)")
                    # strip the marker line so consumers at least get the
                    # digest text rather than the raw marker.
                    rest = text[len(FILE_MARKER):].splitlines()[1:]
                    inj[cid] = "\n".join(rest) or text
                else:
                    inj[cid] = full
    return data
