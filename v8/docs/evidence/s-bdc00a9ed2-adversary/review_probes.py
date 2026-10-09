"""One bounded adversary round at 7f8ebe4d; assertions reproduce observed behavior, not desired behavior.

Copy into tests/adversary_s_bdc00a9ed2/test_review_probes.py before running, so tests/conftest.py isolates the host.
This is review evidence, deliberately outside the normal regression suite: fixing a finding should break its probe.
"""
import importlib.util
import json
import os
import stat
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from edp8 import doc_mirror
from edp8.board import Board
from edp8.doc_tools import DocEdit, _headings, _resolve_section
from edp8.bundles import DocEditArgs
from edp8.service import create_app
from edp8.store import Store


@pytest.fixture
def env(tmp_path):
    store = Store(str(tmp_path / 'board.db'))
    root = tmp_path / 'home' / 'docs'
    store.mirror_root = root
    client = TestClient(create_app(Board(store), admin_token='t'))
    for who in ('arch', 'eng'):
        result = client.post('/v1/participants', headers={'X-Admin': 't'}, json={
            'id': who, 'handle': who, 'type': 'agent', 'role': 'architect' if who == 'arch' else 'engineer'})
        assert result.json()['ok']
    yield client, store, root
    client.close()
    store.close()


def make(env, body='alpha beta'):
    client, store, root = env
    result = client.post('/v1/docs', headers={'X-Participant': 'arch'}, json={
        'doc_type': 'note', 'scope': 'global', 'title': body, 'body_md': body}).json()
    assert result['ok'], result
    did = result['value']['id']
    return did, root / 'global' / (did + '.md')


def edit(env, did, who='eng', **args):
    return env[0].post('/v1/docs/' + did + '/edit', headers={'X-Participant': who}, json=args).json()


def test_publish_failure_commits_db_and_unlocks_old_file(env):
    did, path = make(env)
    before = path.read_text()
    with patch('edp8.doc_mirror.os.replace', side_effect=PermissionError('simulated Windows sharing violation')):
        result = edit(env, did, old_string='alpha', new_string='NEW')
    assert result['ok']
    assert env[1].get('doc', did).version == 2
    assert path.read_text() == before
    assert os.access(path, os.W_OK)
    path.write_text('native edit now succeeds')
    print('F1: success receipt v2; DB v2; mirror v1; native write succeeds after failed replace')


@pytest.mark.skipif(os.name != 'nt', reason='Windows reader handle blocks replacement')
def test_real_windows_open_reader_prevents_publish(env):
    did, path = make(env)
    before = path.read_text()
    with path.open('r', encoding='utf-8') as held:
        assert held.read() == before
        result = edit(env, did, old_string='alpha', new_string='NEW')
    assert result['ok']
    assert env[1].get('doc', did).version == 2
    assert path.read_text() == before
    assert os.access(path, os.W_OK)
    print('F1 REAL WINDOWS: ordinary open reader handle leaves DB v2, file v1 writable; no injected fault')


def test_failed_transaction_leaves_readable_uncommitted_tmp(env):
    did, path = make(env)
    doc = env[1].get('doc', did)
    doc.version += 1
    doc.body_md = 'UNCOMMITTED_MARKER'
    with patch.object(env[1], '_fts_put_locked', side_effect=RuntimeError('FTS failure')):
        with pytest.raises(RuntimeError):
            env[1].put('doc', doc)
    tmp = path.with_name(path.name + '.tmp')
    assert env[1].get('doc', did).body_md == 'alpha beta'
    assert 'UNCOMMITTED_MARKER' not in path.read_text()
    assert 'UNCOMMITTED_MARKER' in tmp.read_text()
    print('F2: rejected transaction leaves readable version-2 .md.tmp until next write/start')


def test_zero_section_wrong_hit_or_crash():
    lines = '# T\n## Alpha\na\n## Beta\nb\n'.splitlines(keepends=True)
    heads = _headings(lines)
    assert lines[_resolve_section(lines, heads, '0')].strip() == '## Beta'
    with pytest.raises(IndexError):
        _resolve_section(lines, heads, '1.0')
    print('F3: section=0 returns final heading Beta; section=1.0 raises uncaught IndexError')


def test_zero_section_http_500(env):
    did, path = make(env, '# T\n## Alpha\na\n## Beta\nb\n')
    with TestClient(env[0].app, raise_server_exceptions=False) as client:
        result = client.get('/v1/docs/' + did, params={'section': '1.0'}, headers={'X-Participant': 'eng'})
    assert result.status_code == 500
    print('F3 HTTP: section=1.0 returns 500 instead of section_match candidates')


def test_guest_cannot_read_mirror_via_http(env):
    did, path = make(env, 'PRIVATE_SCOPE_TEST_MARKER')
    client = env[0]
    r = client.post('/v1/participants', headers={'X-Admin': 't'}, json={
        'id': 'visitor', 'handle': 'visitor', 'type': 'human', 'role': 'guest'})
    assert r.json()['ok']
    denied = client.get('/v1/docs/' + did, headers={'X-Participant': 'visitor'})
    assert denied.status_code == 404, denied.text
    allowed = client.get('/v1/docs/' + did, headers={'X-Participant': 'eng'})
    assert allowed.json()['ok'] and 'PRIVATE_SCOPE_TEST_MARKER' in allowed.text
    assert 'PRIVATE_SCOPE_TEST_MARKER' in path.read_text()
    for url in ['/docs/global/' + did + '.md', '/ui/docs/global/' + did + '.md']:
        response = client.get(url, headers={'X-Participant': 'visitor'})
        assert 'PRIVATE_SCOPE_TEST_MARKER' not in response.text
    print('PASS: guest HTTP doc read denied 404; no mirror URL exposes body; local eng already reads it via HTTP')


def test_mirror_reader_has_no_stale_version_guard(env):
    did, path = make(env, 'apple')
    held = path.read_text()
    assert 'version: 1' in held
    assert edit(env, did, who='arch', old_string='apple', new_string='apple apple')['ok']
    result = edit(env, did, old_string='apple', new_string='orange', replace_all=True)
    assert result['ok']
    assert env[1].get('doc', did).body_md == 'orange orange'
    print('Q1: mirror-only reader holds v1 but edits both v2 occurrences without conflict')


def test_two_http_readers_concurrent_edit(env):
    did, path = make(env)
    for who in ('arch', 'eng'):
        assert env[0].get('/v1/docs/' + did, headers={'X-Participant': who}).json()['ok']
    def run(who):
        return edit(env, did, who=who, old_string='alpha', new_string=who)
    with ThreadPoolExecutor(max_workers=2) as ex:
        results = list(ex.map(run, ['arch', 'eng']))
    assert sum(r['ok'] for r in results) == 1
    assert next(r for r in results if not r['ok'])['error']['code'] == 'version_conflict'
    print('PASS: concurrent HTTP readers produce one edit and one version_conflict')


@pytest.mark.parametrize('model', [DocEdit, DocEditArgs])
def test_alias_collisions_refused(model):
    extra = {'id': 'note-x'} if model is DocEditArgs else {}
    for fields in [
        {'old_string': 'a', 'old_text': 'b', 'new_string': 'c'},
        {'edits': [{'old_string': 'a', 'old_text': 'b', 'new_string': 'c'}]},
        {'old_string': 'a', 'new_string': 'b', 'edits': [{'old_text': 'a', 'new_text': 'd'}]},
    ]:
        with pytest.raises(ValueError):
            model(**extra, **fields)


def test_scope_and_id_traversal_blocked(tmp_path):
    root = tmp_path / 'docs'
    for scope in ['../../outside', 'C:\\Windows', '/absolute', '.', '..', 'domain:ops']:
        for did in ['../../note', 'C:\\other', '/note', '..', 'note-valid']:
            path = doc_mirror.mirror_path(root, SimpleNamespace(scope=scope, id=did))
            assert root.resolve() in path.resolve().parents
    print('PASS: 30 scope/id traversal combinations stay under mirror root')


def test_baseline_counts_failed_write_as_change(tmp_path):
    repo = next(p for p in Path(__file__).resolve().parents if (p / 'scripts/doc_call_baseline.py').is_file())
    script = repo / 'scripts' / 'doc_call_baseline.py'
    spec = importlib.util.spec_from_file_location('review_baseline', script)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    rows = [
        {'timestamp': '2026-10-08T12:00:00Z', 'message': {'content': [{
            'type': 'tool_use', 'id': 'one', 'name': 'mcp__edp8__doc_edit',
            'input': {'id': 'note-x', 'old_string': 'missing', 'new_string': 'no change'}}]}},
        {'timestamp': '2026-10-08T12:00:01Z', 'message': {'content': [{
            'type': 'tool_result', 'tool_use_id': 'one', 'is_error': True, 'content': 'edit_match'}]}},
    ]
    (tmp_path / 'one.jsonl').write_text('\n'.join(json.dumps(r) for r in rows), encoding='utf-8')
    result = module.scan(tmp_path, None, None)
    assert result['doc_changes'] == 1 and result['doc_call_errors'] == 1
    assert result['median_bytes_per_change'] > 0
    print('F4: zero successful changes => doc_changes=1 and non-null median_bytes_per_change')


def test_baseline_day_boundary_drops_error(tmp_path):
    repo = next(p for p in Path(__file__).resolve().parents if (p / 'scripts/doc_call_baseline.py').is_file())
    script = repo / 'scripts' / 'doc_call_baseline.py'
    spec = importlib.util.spec_from_file_location('review_baseline2', script)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    rows = [
        {'timestamp': '2026-10-08T23:59:59Z', 'message': {'content': [{
            'type': 'tool_use', 'id': 'one', 'name': 'mcp__edp8__doc_edit', 'input': {}}]}},
        {'timestamp': '2026-10-09T00:00:01Z', 'message': {'content': [{
            'type': 'tool_result', 'tool_use_id': 'one', 'is_error': True, 'content': 'validation error'}]}},
    ]
    (tmp_path / 'one.jsonl').write_text('\n'.join(json.dumps(r) for r in rows), encoding='utf-8')
    before = module.scan(tmp_path, None, '2026-10-09')
    after = module.scan(tmp_path, '2026-10-09', None)
    assert before['doc_calls'] == 1 and before['doc_call_errors'] == 0
    assert after['doc_calls'] == 0 and after['doc_call_errors'] == 0
    print('F4: failed call spanning midnight counted as 0 errors in both adjacent windows')


def test_backfill_failed_publish_is_reported_written(env):
    did, path = make(env)
    os.chmod(path, stat.S_IWRITE | stat.S_IREAD)
    path.write_text('outdated')
    with patch('edp8.doc_mirror.os.replace', side_effect=PermissionError('sharing violation')):
        result = doc_mirror.backfill(env[1], env[2])
    assert result == {'written': 1, 'same': 0, 'failed': 0}
    assert path.read_text() == 'outdated'
    print('F1: backfill failed rename reports written=1 failed=0')


def test_backfill_scale_and_cleanup(tmp_path):
    store = Store(str(tmp_path / 'scale.db'))
    from edp8.schemas import Doc
    for n in range(600):
        store.put('doc', Doc(id=f'note-scale-{n}', created_by='arch', doc_type='note',
                            title=f'Scale {n}', body_md='x' * 8192, scope='global', owner_role='architect'))
    root = tmp_path / 'docs'
    stale = root / 'global' / 'stale.md.tmp'
    stale.parent.mkdir(parents=True)
    stale.write_text('stale')
    start = time.perf_counter()
    first = doc_mirror.backfill(store, root)
    elapsed = time.perf_counter() - start
    second = doc_mirror.backfill(store, root)
    assert first == {'written': 600, 'same': 0, 'failed': 0}
    assert second == {'written': 0, 'same': 600, 'failed': 0}
    assert not stale.exists()
    print(f'PASS: backfill 600 docs/~4.9MB in {elapsed:.3f}s; repeat same=600; stale tmp removed')
    store.close()
