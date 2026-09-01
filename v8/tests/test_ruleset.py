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
    out = assemble_ruleset(load, ext, ["leaf"])
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
    out = assemble_ruleset(load, ext, ["d"])
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
