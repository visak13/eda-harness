"""Explicit-run (S13 F8): the default ticket_read on this epic's real-board snapshot against the old default.

Run: S13_SNAPSHOT=<read-only SQLite backup> pytest tests/s13_ticket_read_size.py -s. The snapshot is private
and never committed; the test copies it to tmp and reads only.
"""
import json
import os
import shutil
from pathlib import Path

import pytest

from edp8 import broker_adapter
from edp8.bundles import TICKET_FULL_INCLUDE
from edp8.store import Store
import test_s9_tool_matrix as scenarios

EPIC = 'epic-0cec8d1c31'
OLD_DEFAULT = 41748  # S13 audit: the pre-F8 default ticket_read on EPIC, bytes


def _size(out):
    return len(json.dumps(out, ensure_ascii=True, default=str))


def test_compact_ticket_read_on_snapshot(monkeypatch, tmp_path):
    snapshot = Path(os.environ.get('S13_SNAPSHOT', '.data/s13/board-snapshot.db'))
    if not snapshot.is_file():
        pytest.skip('set S13_SNAPSHOT to the read-only board snapshot')
    working = tmp_path / 'audit.db'
    shutil.copy2(snapshot, working)
    store = Store(str(working))
    store.delete('participant', 'owner')
    monkeypatch.setattr(scenarios, 'Store', lambda _: store)
    monkeypatch.setattr(broker_adapter, 'publish', lambda *a, **kw: True)
    world = scenarios.World(monkeypatch, tmp_path)
    compact = world.call('architect', 'ticket_read', {'ticket_id': EPIC})
    more = {k: v for k, v in compact['value']['more'].items() if k != 'tool'}
    full = world.call('architect', 'ticket_read', more)
    old = world.call('architect', 'ticket_read', {'ticket_id': EPIC, 'include': TICKET_FULL_INCLUDE})
    print(json.dumps({'compact': _size(compact), 'continuation': _size(full), 'old_default': OLD_DEFAULT,
                      'omitted': compact['value']['omitted']}))
    assert _size(compact) <= OLD_DEFAULT // 2
    assert full['value'] == old['value']
    for key in ('words', 'chain', 'children', 'thread', 'links', 'criteria', 'docs'):
        assert key in full['value']
