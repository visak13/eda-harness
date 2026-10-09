"""Selected-finding recheck at 0f8fab4d; residual probes assert the observed failure, not desired behavior.

Copy to tests/adversary_s_bdc00a9ed2/test_recheck.py so the host-isolating tests/conftest.py fixtures apply.
"""
import importlib.util
import os
from pathlib import Path
from unittest.mock import patch

import pytest

REPO = next(p for p in Path(__file__).resolve().parents if (p / 'scripts/doc_call_baseline.py').is_file())
spec = importlib.util.spec_from_file_location('original_review', REPO / 'docs/evidence/s-bdc00a9ed2-adversary/review_probes.py')
original = importlib.util.module_from_spec(spec)
spec.loader.exec_module(original)
env = original.env
make, edit = original.make, original.edit


@pytest.mark.skipif(os.name != 'nt', reason='Windows sharing semantics')
def test_f1_readonly_restored_but_nondoc_commit_does_not_drain_queue(env):
    did, path = make(env)
    with path.open('r'):
        result = edit(env, did, old_string='alpha', new_string='NEW')
        assert result['ok'] and did in env[1].mirror_pending
        assert not os.access(path, os.W_OK)
        with pytest.raises(PermissionError):
            path.write_text('native edit')
    participant = env[1].get('participant', 'eng')
    participant.location = 'next committed record'
    env[1].put('participant', participant)
    assert env[1].get('participant', 'eng').location == 'next committed record'
    assert did in env[1].mirror_pending and 'NEW' not in path.read_text()
    make(env, 'another doc commit')
    assert did not in env[1].mirror_pending and 'NEW' in path.read_text()
    assert not os.access(path, os.W_OK)
    print('F1 PARTIAL: real held-reader protection restored; non-doc commit does not repair; next doc commit does')


def test_f2_stage_fsync_failure_leaves_uncommitted_body(env):
    did, path = make(env)
    before = path.read_text()
    doc = env[1].get('doc', did)
    doc.version += 1
    doc.body_md = 'UNCOMMITTED_STAGE_FAILURE_MARKER'
    with patch('edp8.doc_mirror.os.fsync', side_effect=OSError('simulated storage I/O failure')):
        with pytest.raises(OSError):
            env[1].put('doc', doc)
    assert env[1].get('doc', did).body_md == 'alpha beta'
    assert path.read_text() == before
    leftovers = [p for p in env[2].rglob('*') if p.is_file() and 'UNCOMMITTED_STAGE_FAILURE_MARKER' in p.read_text()]
    assert len(leftovers) == 1 and leftovers[0].parent.name == '.staging'
    print('F2 RESIDUAL: stage fsync raises; DB rolls back; .staging temp retains full uncommitted body')


def test_f2_outer_rollback_after_successful_stage_cleans_temp(env):
    did, path = make(env)
    with pytest.raises(RuntimeError):
        with env[1].transaction():
            doc = env[1].get('doc', did)
            doc.body_md = 'OUTER_ROLLBACK_MARKER'
            doc.version += 1
            env[1].put('doc', doc)
            raise RuntimeError('outer rollback')
    assert not list((env[2] / '.staging').glob('*'))
    assert env[1].get('doc', did).body_md == 'alpha beta'
    print('F2 PASS: successful stage followed by outer rollback cleans staged body')


def test_f3_http_invalid_selectors(env):
    did, path = make(env, '# T\n## Alpha\na\n## Beta\nb\n')
    for section in ('0', '-1', '1.0', '1.-2'):
        response = env[0].get('/v1/docs/' + did, params={'section': section}, headers={'X-Participant': 'eng'})
        assert response.status_code < 500
        payload = response.json()
        assert not payload['ok'] and payload['error']['code'] == 'section_match'
        assert 'count from 1' in payload['hint']
    print('F3 PASS: four invalid positional selectors refused with hint, no 500')


def test_q1_mirror_pin_warning_and_explicit_stale_rejection(env):
    did, path = make(env, 'apple')
    assert 'version: 1' in path.read_text()
    assert edit(env, did, who='arch', old_string='apple', new_string='apple apple')['ok']
    stale = edit(env, did, expected_version=1, old_string='apple', new_string='orange', replace_all=True)
    assert not stale['ok'] and stale['error']['code'] == 'version_conflict'
    unpinned = edit(env, did, old_string='apple', new_string='orange', replace_all=True)
    assert unpinned['ok'] and 'version_pin' in unpinned['value']
    assert 'expected_version' in unpinned['hint'] and 'front-matter' in unpinned['hint']
    print('Q1 PASS: stale explicit pin rejected; unserved edit warns latest-version fallback and names front matter')
