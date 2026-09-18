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
