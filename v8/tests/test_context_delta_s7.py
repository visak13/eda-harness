"""Isolated additive context protocol tests, including byte measurements."""
import json
from concurrent.futures import ThreadPoolExecutor

from test_context_tools import board, client, rig, H

ENG = {'X-Participant': 'eng'}


def snapshot(client):
    return client.get('/v1/context', headers=ENG).json()['value']


def delta(client, cursor, **kw):
    return client.get('/v1/context_delta', headers=ENG, params={'cursor': cursor, **kw}).json()


def send(client, rig, text='new', **kw):
    return client.post('/v1/messages', headers=H, json={'ticket_id': rig['t1']['id'],
                       'kind': 'note', 'text': text, **kw}).json()['value']


def test_empty_sparse_pages_replay_and_bytes(client, rig):
    for i in range(8):
        send(client, rig, f'baseline {i}: ' + 'existing discussion ' * 10)
    full = snapshot(client)
    empty = delta(client, full['cursor'])['value']
    assert set(empty) == {'changed', 'next_cursor', 'has_more'}
    assert not empty['changed'] and not empty['has_more']
    ids = [send(client, rig, f'item {i}')['id'] for i in range(5)]
    first = delta(client, full['cursor'], limit=2)['value']
    assert first == delta(client, full['cursor'], limit=2)['value']
    got = [c['object_id'] for c in first['changes']]
    # Inserts after page one do not alter its frozen continuation boundary.
    late = send(client, rig, 'late')['id']
    page = first
    while page['has_more']:
        page = delta(client, page['next_cursor'], limit=2)['value']
        got.extend(c['object_id'] for c in page.get('changes', []))
    assert got == ids
    assert [c['object_id'] for c in delta(client, page['next_cursor'])['value']['changes']] == [late]
    legacy = {k: v for k, v in full.items() if k != 'cursor'}
    sizes = {name: len(json.dumps(value).encode()) for name, value in [('legacy_full', legacy), ('full', full), ('empty', empty), ('sparse', first)]}
    print('context serialized bytes / ceil(bytes/4) estimated tokens:', sizes,
          {k: (v + 3) // 4 for k, v in sizes.items()})
    assert sizes['empty'] < sizes['legacy_full'] and sizes['sparse'] < sizes['legacy_full']


def test_doc_refs_asks_and_truncation(client, rig):
    # Link doc directly to assigned task.
    client.post('/v1/links', headers=H, json={'from_id': rig['t1']['id'], 'to_id': rig['doc']['id'], 'relation': 'designed_by'})
    base = snapshot(client)
    ask = send(client, rig, 'Q' * 1000, kind='question', to='eng')
    client.patch(f"/v1/docs/{rig['doc']['id']}", headers=H, json={'body_md': 'new design'})
    out = delta(client, base['cursor'])['value']
    assert out['asks_changed']['read_ref']['tool'] == 'inbox'
    message = next(x for x in out['changes'] if x['object_id'] == ask['id'])
    assert message['truncated'] and len(message['text']) == 512
    doc = next(x for x in out['changes'] if x['object_id'] == rig['doc']['id'])
    assert doc['version'] == 2 and 'body_md' not in doc
    assert snapshot(client)['asks_for_me'][0]['id'] == ask['id']
    send(client, rig, 'done', kind='answer', reply_to=ask['id'])
    resolved = delta(client, out['next_cursor'])['value']
    assert resolved['asks_changed'] and not snapshot(client)['asks_for_me']


def test_resync_invalid_identity_scope_expiry_reset_and_assignment(board, client, rig):
    base = snapshot(client)['cursor']
    assert delta(client, base + 'tamper')['error']['code'] == 'resync_required'
    assert delta(client, base, ticket_id=rig['t1']['id'])['error']['code'] == 'resync_required'
    other = client.get('/v1/context_delta', headers=H, params={'cursor': base}).json()
    assert other['error']['code'] == 'resync_required'
    reader = board._context_reader()
    state = reader._decode(base)
    assert delta(client, reader._encode({**state, 'at': 0}))['error']['code'] == 'resync_required'
    reader.key = b'another generation'
    assert delta(client, base)['error']['code'] == 'resync_required'
    base = snapshot(client)['cursor']
    client.patch(f"/v1/tickets/{rig['t1']['id']}", headers=H, json={'assignee': 'arch'})
    assert delta(client, base)['error']['code'] == 'resync_required'


def test_retention_auth_removal_and_unknown_event(board, client, rig):
    from edp8.schemas import Event, EventKind
    base = snapshot(client)['cursor']
    state = board._context_reader()._decode(base)
    board.store.delete('event', state['anchor'])
    assert delta(client, base)['error']['code'] == 'resync_required'
    base = snapshot(client)['cursor']
    # Unknown object event remains an explicit invalidation, not silently omitted.
    event = Event(id='ev-unknown', subject_id='unknown-object', kind=EventKind.doc_updated,
                  data={'mentions': ['eng']})
    board.store.put('event', event)
    out = delta(client, base)['value']
    assert out['changed'] and 'resynchronize' in out['changes'][0]['action']
    board.store.delete('participant', 'eng')
    assert not delta(client, out['next_cursor'])['ok']


def test_snapshot_concurrent_insertion_never_loses_message(client, rig):
    with ThreadPoolExecutor(max_workers=2) as pool:
        snap_future = pool.submit(snapshot, client)
        msg_future = pool.submit(send, client, rig)
        snap, msg = snap_future.result(), msg_future.result()
    inline = {m['id'] for ticket in snap['tickets'] for m in ticket['thread']}
    changed = {c['object_id'] for c in delta(client, snap['cursor'])['value'].get('changes', [])}
    assert msg['id'] in inline | changed


def test_non_event_mutations_invalidate_orientation(client, rig):
    base = snapshot(client)['cursor']
    client.post('/v1/links', headers=H, json={'from_id': rig['t1']['id'], 'to_id': rig['doc']['id'], 'relation': 'designed_by'})
    out = delta(client, base)['value']
    assert out['changed'] and out['orientation_changed']
    base = snapshot(client)['cursor']
    created = client.post('/v1/criteria', headers=ENG, json={'ticket_id': rig['t1']['id'], 'text': 'new check', 'check': 'command'}).json()
    assert created['ok'], created
    assert delta(client, base)['value']['orientation_changed']
    base = snapshot(client)['cursor']
    client.patch(f"/v1/tickets/{rig['t1']['id']}", headers=H, json={'description': 'new description'})
    assert delta(client, base)['value']['orientation_changed']


def test_oversized_event_cannot_stall_and_response_is_bounded(board, client, rig):
    from edp8.schemas import Participant, Role, MessageKind
    huge = Participant(id='a' * 49000, handle='large-author', type='human', role=Role.owner)
    board.store.put('participant', huge)
    base = snapshot(client)['cursor']
    board.message_send(huge, ticket_id=rig['t1']['id'], to=None, kind=MessageKind.note, text='large actor')
    out = delta(client, base)['value']
    assert out['changed'] and not out['has_more']
    assert out['changes'][0]['truncated'] and out['next_cursor'] != base
    base = snapshot(client)['cursor']
    for i in range(100):
        send(client, rig, 'X' * 512)
    out = delta(client, base, limit=100)
    assert len(json.dumps(out).encode()) <= 48000
    assert out['value']['has_more']


def test_irrelevant_changes_suppressed(client, rig):
    base = snapshot(client)['cursor']
    client.post('/v1/docs', headers=H, json={'doc_type': 'note', 'title': 'unrelated', 'body_md': 'private noise', 'scope': 'global'})
    out = delta(client, base)['value']
    assert not out['changed'] and 'changes' not in out
