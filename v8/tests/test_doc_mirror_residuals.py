"""s-bdc00a9ed2 Astra recheck residuals (report-296868be2a): a failed stage leaves no uncommitted body on disk, and any
commit (not only a doc's) repairs a mirror file a held reader kept stale. Fixtures come from Astra's committed
review probes (docs/evidence/s-bdc00a9ed2-adversary/review_probes.py)."""
import importlib.util
import os
from pathlib import Path
from unittest.mock import patch

import pytest

_REPO = Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location(
    "s_bdc_review_probes", _REPO / "docs/evidence/s-bdc00a9ed2-adversary/review_probes.py")
_probes = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_probes)
env = _probes.env
make, edit = _probes.make, _probes.edit


@pytest.mark.skipif(os.name != "nt", reason="Windows sharing semantics")
def test_a_non_doc_commit_repairs_a_mirror_file_a_reader_held(env):
    did, path = make(env)
    with path.open("r"):
        assert edit(env, did, old_string="alpha", new_string="NEW")["ok"]
        assert did in env[1].mirror_pending and not os.access(path, os.W_OK)
    participant = env[1].get("participant", "eng")
    participant.location = "next committed record"
    env[1].put("participant", participant)
    assert did not in env[1].mirror_pending and "NEW" in path.read_text()
    assert not os.access(path, os.W_OK)


def test_a_failed_stage_leaves_no_uncommitted_body_on_disk(env):
    did, path = make(env)
    before = path.read_text()
    doc = env[1].get("doc", did)
    doc.version += 1
    doc.body_md = "UNCOMMITTED_STAGE_FAILURE_MARKER"
    with patch("edp8.doc_mirror.os.fsync", side_effect=OSError("simulated storage I/O failure")):
        with pytest.raises(OSError):
            env[1].put("doc", doc)
    assert env[1].get("doc", did).body_md == "alpha beta"
    assert path.read_text() == before
    assert not [p for p in env[2].rglob("*") if p.is_file() and "UNCOMMITTED_STAGE_FAILURE_MARKER" in p.read_text()]
