"""S13 round-1 regressions F9-F12 (t-dac2a14caf): the adversary's S17 probes from report-b020cd0eca v2 (evidence
commit 2c4564c6), moved into the default suite. F9 follows the architect's ruling (advisory, no parsing, no
enforcement): an unverified summary_first head carries the advisory note, not a warning."""
import json

import pytest

from test_s17_summary_first import http, _doc, _call, BIG, ARCH
from edp8.schemas import LEGACY_WARNING


@pytest.mark.parametrize('opening', ['## Purpose\nGeneral background only.',
                                     '## Reading strategy\nRead the introduction first.'])
def test_f9_unverified_summary_first_head_is_advisory(http, opening):
    body = '# Synthetic contract\n' + opening + '\n\n' + ('Ordinary background.\n' * 700)
    body += '\n## Release constraints\nMUST obtain the synthetic release permit before shipping.\n'
    did = _doc(http, body=body)
    head = _call(http, 'eng', 'doc_read', id=did)['value']
    assert 'synthetic release permit' not in head['body_md']
    assert head['layout'] == 'summary_first'
    assert not head.get('warning')  # F9 ruling: never a parsed verdict on the body
    assert 'not checked' in head['note'] and 'sections' in head['note'], 'the head promises nothing it cannot check'


def test_f11_agent_cannot_take_human_whole_body_http_shortcut(http):
    did = _doc(http)
    r = http.get(f'/v1/docs/{did}', params={'all': 'true'}, headers={'X-Participant': 'eng'})
    assert r.status_code in (401, 403) or r.json()['value'].get('body_md') != BIG, \
        'an authenticated agent reads the whole doc through HTTP all=true'


def test_f10_mcp_doc_query_keeps_legacy_warning(http):
    did = _doc(http, layout='legacy')
    out = _call(http, 'eng', 'doc_query', scope='global')
    assert did in json.dumps(out)
    assert LEGACY_WARNING in json.dumps(out), 'MCP row projection drops legacy warning'


def test_f10_f11_mcp_update_full_echo_keeps_warning_and_is_bounded(http):
    did = _doc(http, layout='legacy')
    out = _call(http, 'arch', 'doc_update', id=did, tags=['synthetic'], compact=False)
    assert out['ok']
    observed = {'warning': LEGACY_WARNING in json.dumps(out),
                'bounded': len(out['value'].get('body_md', '')) <= 8192}  # F11: an agent gets the receipt
    assert all(observed.values()), f'full doc_update echo: {observed}'


def test_f12_search_hit_section_can_be_read_with_repeated_heading(http):
    body = '# Contract\n## Linux\n### Install\nordinary steps\n## Windows\n### Install\nzephyrquartz required\n'
    did = _doc(http, body=body)
    hits = _call(http, 'eng', 'find', query='zephyrquartz', types='doc')['value']
    hit = next(h for h in hits if h['id'] == did)
    out = _call(http, 'eng', 'doc_read', id=did, section=hit['section'])
    assert out['ok'], f"find returns ambiguous section {hit['section']!r}: {out}"
    assert 'zephyrquartz' in out['value']['body_md']


def test_child_map_skipped_levels_preserves_every_direct_child(http):
    did = _doc(http, body='# Contract\n## Parent\nown\n#### A\na\n### B\nb\n#### C\nc\n')
    out = _call(http, 'eng', 'doc_read', id=did, section='## Parent')['value']
    assert out['body_md'] == '## Parent\nown\n'
    assert [r['h'] for r in out['children']] == ['#### A', '### B']


def test_version_pinned_pages_recover_all_hidden_obligations(http):
    body = '# Contract\n' + 'Background only.\n' * 1000 + '\n## Rule\nMUST obtain zephyrquartz permit.\n'
    did = _doc(http, body=body, layout='legacy')
    head = _call(http, 'eng', 'doc_read', id=did)['value']
    collected = head['body_md']
    args = head['continuation']['page']
    while args:
        part = _call(http, 'eng', 'doc_read', **args)['value']
        assert part['version'] == head['version'] and part['warning'] == LEGACY_WARNING
        collected += part['body_md']
        args = part.get('continuation')
    assert collected == body


def test_paragraph_only_deep_search_returns_the_doc(http):
    did = _doc(http, body=('background. ' * 1200) + '\n\nzephyrquartz must be retained\n')
    hits = _call(http, 'eng', 'find', query='zephyrquartz', types='doc')['value']
    assert did in [h['id'] for h in hits]


def test_lookup_excerpt_preserves_legacy_warning(http):
    result = http.post('/v1/tickets', headers={'X-Participant': 'owner'},
                       json={'kind': 'epic', 'work_type': 'feature', 'title': 'Private lookup scenario'}).json()
    assert result['ok'], result
    epic = result['value']['id']
    did = _doc(http, body='# Legacy\n## Deep\nzephyrquartz must be retained.\n', scope=epic, layout='legacy')
    out = _call(http, 'eng', 'lookup', scope=epic, question='zephyrquartz')
    assert out['ok'] and did in json.dumps(out), out
    assert LEGACY_WARNING in json.dumps(out)


def test_f12_map_names_a_repeated_heading_by_its_path_and_a_bare_one_says_which(http):
    body = '# Contract\n' + 'Background.\n' * 800 + '## Linux\n### Install\nlinux steps\n## Windows\n### Install\nwin steps\n'
    did = _doc(http, body=body)
    head = _call(http, 'eng', 'doc_read', id=did)['value']
    hs = [m['h'] for m in head['map']]
    assert '## Linux > ### Install' in hs and '## Windows > ### Install' in hs and '## Windows' in hs
    out = _call(http, 'eng', 'doc_read', id=did, section='## Windows > ### Install')['value']
    assert out['body_md'] == '### Install\nwin steps\n'
    bad = _call(http, 'eng', 'doc_read', id=did, section='### Install')
    assert not bad['ok'] and '## Windows > ### Install' in bad['error']['message']


def test_f10_write_echoes_carry_layout_and_the_legacy_warning(http):
    did = _doc(http, layout='legacy')
    cur = http.get(f'/v1/docs/{did}', params={'all': 'true'}, headers={'X-Participant': 'owner'}).json()['value']
    edit = _call(http, 'arch', 'doc_edit', id=did, expected_version=cur['version'],
                 edits=[{'old_text': cur['body_md'][:20], 'new_text': cur['body_md'][:20]}])['value']
    upd = http.patch(f'/v1/docs/{did}', json={'tags': ['x']}, headers={'X-Participant': 'owner'}).json()['value']
    for echo in (edit, upd):
        assert echo['layout'] == 'legacy' and echo['warning'] == LEGACY_WARNING, echo
    assert upd['body_md'] == cur['body_md']  # a person's full echo is still whole (F11 bounds agents only)


def test_f12_residual_preexisting_s17_section_index_is_rebuilt_with_paths(tmp_path):
    """S13 F12 residual (adversary m-fea8e76214, architect m-10b64902e7): an index S17 wrote with bare repeated
    headings is rebuilt once at open, so a find hit's section reads back."""
    from fastapi.testclient import TestClient
    from edp8.board import Board
    from edp8.schemas import DocType
    from edp8.service import create_app
    from edp8.store import Store
    path = str(tmp_path / 'existing-s17.db')
    store = Store(path)
    board = Board(store)
    owner = board.participant_create('human', 'owner', 'owner', id_='owner')
    board.participant_create('agent', 'engineer', 'eng', id_='eng')
    body = '# Contract\n## Linux\n### Install\nordinary steps\n## Windows\n### Install\nzephyrquartz required\n'
    doc = board.doc_create(owner, doc_type=DocType.note, title='Existing S17 doc', scope='global', body_md=body)
    # S17 before F12: bare heading strings and no format mark
    store._conn.execute("UPDATE fts SET sec='### Install' WHERE id=? AND sec LIKE '%### Install'", (doc.id,))
    store._conn.execute("DELETE FROM store_meta")
    store._conn.commit()
    store.close()
    reopened = Store(path)
    try:
        http = TestClient(create_app(Board(reopened), admin_token='synthetic'))
        hits = _call(http, 'eng', 'find', query='zephyrquartz', types='doc')['value']
        hit = next(h for h in hits if h['id'] == doc.id)
        assert hit['section'] == '## Windows > ### Install'
        result = _call(http, 'eng', 'doc_read', id=doc.id, section=hit['section'])
        assert result['ok'] and 'zephyrquartz' in result['value']['body_md']
    finally:
        reopened.close()
    again = Store(path)  # the mark is set: a second open does not rebuild
    try:
        assert again._conn.execute("SELECT v FROM store_meta WHERE k='fts_sec'").fetchone()[0]
    finally:
        again.close()
