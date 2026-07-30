"""Compose N compiled specialist docs into one worker grounding.

MULTI-SPEC worker selection (2026-06-03, recipe …-s14), amendment A3.

An action may carry MORE THAN ONE spec_id (a cross-stack task = e.g. Java +
React). A fresh worker loads each spec's compiled doc and CONCATENATES them
into a single grounding. Per amendment A3 there is **no universal-layer
dedup**: the composition is a simple ORDERED CONCATENATION, each doc under a
clear per-stack section header. The universal foundation repeating across the
stacks is ACCEPTED — noisier, never wrong. (`compiled.md` authoring is
unchanged; nothing about the doc format changed.)

This module is pure (no IO) so it is trivially testable; the
`get_specialist_docs` tool wires it to the spec store, and the `/worker`
skill calls that tool with its action's effective spec_ids.
"""

# Per-stack section header. Stable + greppable so a reviewer (or a test) can
# locate each stack's block in the composed grounding.
_STACK_HEADER = "# ===== Specialist stack: {spec_id} ====="


def compose_specialist_docs(parts: list[tuple[str, str | None]]) -> str:
    """Compose ordered (spec_id, compiled_doc) pairs into one grounding.

    - N == 0 (or every doc missing) → "" (caller takes the generic path).
    - N == 1 → that doc's content returned UNCHANGED (bit-for-bit identical
      to the single-spec path that shipped before multi-spec: no header, no
      banner, no wrapper). This is the backward-compatibility guarantee.
    - N >= 2 → a one-line composed banner, then each present doc under its
      per-stack header, joined in input order. The universal layer repeats
      per stack by design (amendment A3 — no dedup).

    Docs whose content is None (spec absent / not compiled) are skipped here;
    Guard B already fails the spawn closed before a worker reaches this point,
    so in practice every stamped spec has a doc — the skip is just defensive.
    """
    present = [(spec_id, content) for spec_id, content in parts
               if content is not None]
    if not present:
        return ""
    if len(present) == 1:
        # Single-spec: return the doc verbatim — identical to pre-multi-spec.
        return present[0][1]

    banner = (
        f"<!-- COMPOSED GROUNDING: {len(present)} specialist docs, ordered "
        f"concatenation. The universal foundation repeats per stack by design "
        f"(no dedup); honor EVERY stack's [required]/[expected] rules. -->"
    )
    blocks = [banner]
    for spec_id, content in present:
        blocks.append(f"{_STACK_HEADER.format(spec_id=spec_id)}\n\n{content}")
    return "\n\n".join(blocks)
