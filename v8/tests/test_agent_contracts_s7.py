"""S7 additive tool contracts: legacy defaults pinned before implementation."""
import pytest

from test_context_tools import board, client, rig, H
from edp8.bundles import ALL_TOOLS, bind_request, invoke
from edp8.client import BoardClient


def test_legacy_document_defaults(client, rig):
    doc = rig['doc']
    out = client.get(f"/v1/docs/{doc['id']}", headers=H).json()
    assert out['ok'] and out['value']['body_md'] == 'kestrel pilgrim'
    assert out['value']['versions'] == [1]
    updated = client.patch(f"/v1/docs/{doc['id']}", headers=H,
                           json={'body_md': 'updated'}).json()
    assert updated['ok'] and updated['value']['body_md'] == 'updated'
    assert updated['value']['version'] == 2
    old = client.get(f"/v1/docs/{doc['id']}?version=1", headers=H).json()
    assert old['value']['body_md'] == 'kestrel pilgrim'


def test_legacy_context_and_discovery(client, rig):
    snapshot = client.get('/v1/context', headers={'X-Participant': 'eng'}).json()['value']
    assert {'participant', 'tickets', 'asks_for_me', 'hint'} <= snapshot.keys()
    assert snapshot['tickets'][0]['ticket']['id'] == rig['t1']['id']
    with bind_request(BoardClient(participant='eng', client=client)):
        out = invoke(ALL_TOOLS['describe'], {'type': 'doc'})
    assert out['ok'] and 'doc_update' in out['value']['tools']
    assert {'doc_read', 'doc_update', 'context', 'message_send'} <= ALL_TOOLS.keys()


def test_atomic_edits_and_bounded_read(client, rig):
    id_ = rig['doc']['id']
    url = f'/v1/docs/{id_}'
    body = '# First\nunique alpha\n# Second\nunique beta\n'
    client.patch(url, headers=H, json={'body_md': body})
    def edit(edits, version=2, headers=H):
        return client.post(url + '/edit', headers=headers,
                           json={'expected_version': version, 'edits': edits}).json()
    assert edit([{'old_text': 'alpha', 'new_text': 'A'}, {'old_text': 'missing', 'new_text': ''}])['error']['code'] == 'edit_match'
    assert edit([{'old_text': 'unique', 'new_text': ''}])['error']['code'] == 'edit_match'
    assert edit([{'old_text': 'unique alpha', 'new_text': ''}, {'old_text': 'alpha', 'new_text': ''}])['error']['code'] == 'edit_overlap'
    assert client.get(url, headers=H).json()['value']['version'] == 2
    out = edit([{'old_text': 'alpha', 'new_text': 'A'}, {'old_text': 'beta', 'new_text': 'B'}])
    assert out['ok'] and out['value']['version'] == 3 and 'body_md' not in out['value']
    assert edit([{'old_text': 'A', 'new_text': 'C'}])['error']['code'] == 'version_conflict'
    part = client.get(url, params={'version': 2, 'section': '# First', 'limit': 10}, headers=H).json()['value']
    chunks = part['body_md']
    while part['continuation']:
        params = part['continuation'].copy()
        params.pop('id')
        part = client.get(url, params=params, headers=H).json()['value']
        chunks += part['body_md']
    assert chunks == '# First\nunique alpha\n'
    compact = client.patch(url, headers=H, json={'title': 'new', 'compact': True}).json()['value']
    assert compact['changed_fields'] == ['title'] and 'body_md' not in compact


def test_concurrent_edits_have_one_winner(board, client, rig):
    from concurrent.futures import ThreadPoolExecutor
    from edp8.doc_tools import DocEdit
    from edp8.board import BoardError
    actor = board._get('participant', 'owner', 'participant')
    request = DocEdit(expected_version=1, edits=[{'old_text': 'kestrel', 'new_text': 'eagle'}])
    def run():
        try:
            return board.doc_edit(actor, rig['doc']['id'], request)['version']
        except BoardError as exc:
            return exc.code
    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(lambda _: run(), range(2)))
    assert sorted(map(str, results)) == ['2', 'version_conflict']


def test_doc_permissions_and_measured_savings(client, rig):
    import json
    body = '# Design\n' + 'long body ' * 4000
    doc = client.post('/v1/docs', headers={'X-Participant': 'arch'}, json={
        'doc_type': 'design', 'title': 'design', 'body_md': body, 'scope': rig['epic']['id']}).json()['value']
    url = f"/v1/docs/{doc['id']}"
    denied = client.post(url + '/edit', headers={'X-Participant': 'eng'}, json={
        'expected_version': 1, 'edits': [{'old_text': '# Design', 'new_text': '# New'}]}).json()
    assert denied['error']['code'] == 'scope'
    assert client.get(url, headers=H).json()['value']['version'] == 1
    changed = client.post(url + '/edit', headers={'X-Participant': 'arch'}, json={
        'expected_version': 1, 'edits': [{'old_text': '# Design', 'new_text': '# New'}]}).json()
    assert changed['ok'], changed
    full = client.get(url, headers=H).json()
    narrow = client.get(url, headers=H, params={'limit': 1024}).json()
    sizes = {key: len(json.dumps(out).encode()) for key, out in [('full', full), ('edit', changed), ('range', narrow)]}
    print('document serialized bytes:', sizes)
    assert sizes['edit'] < sizes['full'] / 10 and sizes['range'] < sizes['full'] / 10


def test_discovery_enum_audit_and_future_heartbeat(client, rig):
    from edp8.bundles import ROLE_BUNDLES, _heartbeat_prompt
    with bind_request(BoardClient(participant='eng', client=client)):
        listing = invoke(ALL_TOOLS['describe_objects'], {})
        assert 'ContextDelta' in listing['value']['objects']
        for name in ('doc', 'ContextSnapshot', 'ContextDelta', 'ContextChange'):
            assert invoke(ALL_TOOLS['describe_objects'], {'type': name})['ok']
        for tool, field in [('spawn', 'effort'), ('spawn', 'mode'), ('session_query', 'state')]:
            schema = ALL_TOOLS[tool].args_model.model_json_schema()
            assert '$ref' in json_repr(schema['properties'][field])
    for role in ROLE_BUNDLES:
        assert 'context_delta' in ROLE_BUNDLES[role] and 'describe_objects' in ROLE_BUNDLES[role]
    for role in ('owner', 'architect', 'engineer', 'qa'):
        prompt = _heartbeat_prompt(role + '.ticket')
        assert 'context_delta' in prompt and 'Do not call both routinely' in prompt
        if role in ('engineer', 'qa'):
            assert 'NEXT UNBUILT ITEM' in prompt


@pytest.mark.parametrize('fence', ['```', '~~~~'])
def test_section_read_ignores_fenced_comments(client, rig, fence):
    body = f'# Target\n{fence}python\n# code comment\n{fence}\nkeep this\n# End\nnot target\n'
    url = f"/v1/docs/{rig['doc']['id']}"
    client.patch(url, headers=H, json={'body_md': body})
    read = client.get(url, headers=H, params={'section': '# Target'}).json()['value']
    assert read['body_md'] == body.split('# End')[0]
    assert not read['truncated']
    assert not client.get(url, headers=H, params={'section': '# code comment'}).json()['ok']


def json_repr(value):
    import json
    return json.dumps(value)
