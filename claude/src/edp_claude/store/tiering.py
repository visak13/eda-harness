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

import json
import os
from pathlib import Path

from .atomic import write_atomic

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
        obj[ref_field] = ref
    # The write is content-guarded; the digest substitution is NOT — gating it
    # on the write would leave full text inline and silently untier the field.
    _write_sidecar(root, obj[ref_field], text)
    obj[field] = _digest_line(text, obj[ref_field])


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
            _dehydrate_field(
                acc, "actual", "actual_ref",
                f"evidence/{a.get('action_id', 'unknown')}-actual.md",
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
            already = (plan_dir / ref).exists()
            if not already and (not tier_write_enabled()
                                or len(text.encode("utf-8")) <= _threshold()):
                continue
            _write_sidecar(plan_dir, ref, text)
            inj[cid] = f"{FILE_MARKER}{ref}\n{_digest_line(text, ref)}"
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
