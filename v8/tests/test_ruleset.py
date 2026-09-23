"""assemble_ruleset: layered composition over board docs (v7 mechanism, v8 home)."""

import pytest

from edp8.ruleset import AssembleError, LayerDoc, assemble_ruleset


def _mk(docs: dict[str, str], extends: dict[str, list[str]]):
    def load(doc_id):
        if doc_id not in docs:
            return None
        return LayerDoc(id=doc_id, title=doc_id, doc_type="strategy_ll", body_md=docs[doc_id])

    def extends_of(doc_id):
        return extends.get(doc_id, [])

    return load, extends_of


def test_universal_first_most_specific_last_and_dedupe():
    load, ext = _mk(
        {
            "universal": "- log every failure\n- [ ] tests green",
            "python": "- use pydantic models\n- log every failure",  # restates a universal rule
            "leaf": "- prefer httpx [required]",
        },
        {"leaf": ["python"], "python": ["universal"]},
    )
    out = assemble_ruleset(load, ext, ["leaf"], full=True)
    assert out.layers == ["universal", "python", "leaf"]
    constructive = [x.text.strip() for x in out.constructive]
    assert constructive == ["- log every failure", "- use pydantic models"]
    # the duplicate keeps its most-universal provenance
    assert out.constructive[0].layer == "universal"
    enforced = [x.text.strip() for x in out.enforced]
    assert "- [ ] tests green" in enforced
    assert "- prefer httpx [required]" in enforced


def test_enforced_section_heading():
    load, ext = _mk({"d": "# How\n- build small\n## Enforced checklist\n- every claim has evidence"}, {})
    out = assemble_ruleset(load, ext, ["d"], full=True)
    assert [x.text.strip() for x in out.enforced] == ["- every claim has evidence"]
    assert [x.text.strip() for x in out.constructive] == ["- build small"]


def test_cycle_raises_instruction():
    load, ext = _mk({"a": "x", "b": "y"}, {"a": ["b"], "b": ["a"]})
    with pytest.raises(AssembleError, match="cycle"):
        assemble_ruleset(load, ext, ["a"])


def test_missing_layer_raises_instruction():
    load, ext = _mk({"a": "x"}, {"a": ["ghost"]})
    with pytest.raises(AssembleError, match="does not exist"):
        assemble_ruleset(load, ext, ["a"])


def test_no_leaves_raises():
    load, ext = _mk({}, {})
    with pytest.raises(AssembleError, match="no leaf docs"):
        assemble_ruleset(load, ext, [])


# ---- S-LIBRARY c-6007364edf: no context weight — enforced inlined, every doc one index line
def _tagged(docs: dict[str, tuple[str, list[str]]]):
    def load(doc_id):
        if doc_id not in docs:
            return None
        body, tags = docs[doc_id]
        return LayerDoc(id=doc_id, title=f"T {doc_id}", doc_type="strategy_hl", body_md=body, tags=tags)

    return load, lambda _d: []


def test_brief_inlines_enforced_only_and_indexes_every_doc():
    craft = "\n".join(f"- constructive craft line number {i} with some words" for i in range(400))
    load, ext = _tagged({"a": (craft + "\n- [ ] one enforced bar", ["python", "web"]),
                         "b": ("- only constructive here", [])})
    out = assemble_ruleset(load, ext, ["a", "b"])
    assert out.constructive is None  # not inlined by default
    assert [x.text.strip() for x in out.enforced] == ["- [ ] one enforced bar"]
    assert [x.id for x in out.index] == ["a", "b"]  # a doc with no enforced line is still indexed
    a, b = out.index
    assert a.tags == ["python", "web"] and a.approx_tokens == len(craft + "\n- [ ] one enforced bar") // 4
    assert a.line == f"a · T a (strategy_hl) · python, web · ~{a.approx_tokens} tokens"
    assert "untagged" in b.line
    assert "doc_read" in out.instruction
    # the inlined part is a small fraction of the whole
    assert out.approx_tokens < 200 < out.full_tokens


def test_oversize_applies_to_inlined_part_only():
    huge = "\n".join(f"- craft {i} " + "x" * 200 for i in range(2000))  # ~100k tokens of constructive
    load, ext = _tagged({"a": (huge + "\n- [ ] bar", [])})
    out = assemble_ruleset(load, ext, ["a"])
    assert out.full_tokens > 24_000 and not out.oversize
    enforced_huge = "\n".join(f"- [ ] bar {i} " + "x" * 200 for i in range(2000))
    load2, ext2 = _tagged({"a": (enforced_huge, [])})
    assert assemble_ruleset(load2, ext2, ["a"]).oversize


def test_full_true_restores_constructive():
    load, ext = _tagged({"a": ("- build small\n- [ ] bar", [])})
    out = assemble_ruleset(load, ext, ["a"], full=True)
    assert [x.text for x in out.constructive] == ["- build small"]
