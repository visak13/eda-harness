"""Signed caller-owned context cursors and bounded reference-only event pages.

A process generation is deliberate: a board restart requires a fresh orientation.
No event payload is echoed; current objects/relevance are checked at each read.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import secrets
import time

from .board import BoardError
from .schemas import code_row

MAX_AGE = 86400
MAX_SCAN = 500
MAX_BYTES = 12000        # default page cap in bytes (S20; was 48000) — EDP8_DELTA_BUDGET_B overrides
TEXT_HEAD = 512          # message text carried per change row; read_ref fetches the rest


def delta_budget() -> int:
    """The page byte cap, env-overridable like EDP8_CONTEXT_BUDGET_B (floor 4000)."""
    try:
        return max(4_000, int(os.environ.get("EDP8_DELTA_BUDGET_B", MAX_BYTES)))
    except ValueError:
        return MAX_BYTES


class ContextReader:
    def __init__(self, board):
        self.board = board
        self.key = secrets.token_bytes(32)

    def _encode(self, state):
        raw = json.dumps(state, separators=(',', ':'), sort_keys=True).encode()
        return base64.urlsafe_b64encode(raw + hmac.digest(self.key, raw, 'sha256')).decode()

    def _fail(self, reason):
        raise BoardError('resync_required', reason, 'context() for a new baseline; do not routinely call both tools')

    def _decode(self, token):
        try:
            if len(token) > 65536:
                raise ValueError()
            data = base64.b64decode(token, altchars=b'-_', validate=True)
            raw, signature = data[:-32], data[-32:]
            if not hmac.compare_digest(signature, hmac.digest(self.key, raw, 'sha256')):
                raise ValueError()
            state = json.loads(raw)
            if state['v'] != 1 or time.time() - state['at'] > MAX_AGE:
                raise ValueError()
            return state
        except (ValueError, KeyError, TypeError):
            self._fail('invalid, expired or reset-stream cursor')

    def _roots(self, actor, ticket_id):
        return sorted([self.board.ticket(ticket_id).id] if ticket_id else
                      [t.id for t in self.board.my_tickets(actor)])

    def _asks(self, actor):
        rows = self.board.inbox(actor)
        return hashlib.sha256(json.dumps(rows, sort_keys=True).encode()).hexdigest()

    @staticmethod
    def _digest(value):
        return hashlib.sha256(json.dumps(value, sort_keys=True).encode()).hexdigest()

    def _metadata(self, roots):
        # Legacy mutations do not all emit events (links, criteria, description, deletes).
        # Fingerprint the current orientation without thread history: a bounded invalidation
        # closes that hole without inventing or changing fleet-wide event delivery semantics.
        views = []
        for root in roots:
            views.append({k: v for k, v in self.board.ticket_view(root).items()
                          if k not in ('thread', 'thread_seq', 'thread_total')})
        return self._digest(views)

    def baseline(self, actor, ticket_id):
        roots = self._roots(actor, ticket_id)
        latest = self.board.store.query('event', limit=1, newest_first=True)
        return self._encode({'v': 1, 'at': time.time(), 'p': self._digest(actor.id), 'role': actor.role.value,
                             'scope': self._digest(ticket_id), 'roots': self._digest(roots),
                             'metadata': self._metadata(roots), 'asks': self._asks(actor),
                             'seq': self.board.store.max_seq(), 'through': None,
                             'anchor': latest[0].id if latest else None})

    def _references(self, roots):
        """Objects full context actually includes, including ancestry and blockers."""
        refs = set(roots)
        for root in roots:
            view = self.board.ticket_view(root)
            for name in ('chain', 'children', 'criteria', 'docs', 'links', 'blockers', 'open_gates'):
                for item in view.get(name, []):
                    if isinstance(item, dict):
                        refs.update(item[k] for k in ('id', 'from_id', 'to_id', 'ticket_id')
                                    if isinstance(item.get(k), str))
        return refs

    def delta(self, actor, cursor, ticket_id=None, limit=50):
        if not 1 <= limit <= 100:
            raise BoardError('range', 'limit must be 1..100')
        state = self._decode(cursor)
        if state['p'] != self._digest(actor.id) or state['role'] != actor.role.value or state['scope'] != self._digest(ticket_id):
            self._fail('participant, role or requested scope changed')
        roots = self._roots(actor, ticket_id)
        if self._digest(roots) != state['roots']:
            # Do not return any old-scope content after an assignment/access removal.
            self._fail('context ticket scope changed (assignments added/removed); refresh orientation')
        store = self.board.store
        high = store.max_seq()
        if state.get('anchor') and store.get('event', state['anchor']) is None:
            self._fail('event retention boundary passed or stream reset')
        if state['seq'] > high:
            self._fail('event stream reset')
        first = store.events_since(0, limit=1)
        if first and state['seq'] < first[0][0] - 1:
            self._fail('event retention boundary passed')
        through = state['through'] if state['through'] is not None else high
        refs = self._references(roots)
        changes = []
        cut = None
        consumed = state['seq']
        anchor = state.get('anchor')
        # Reserve the entire protocol envelope, fixed-size hashed cursor and optional
        # invalidations. Remaining bytes include JSON separators, not only row content.
        budget = delta_budget()
        size = len(json.dumps({'ok': True, 'value': {'changed': True, 'next_cursor': cursor,
                              'has_more': True}, 'hint': ''}).encode()) + 1024
        if size >= budget:
            self._fail('cursor cannot fit the bounded response; refresh orientation')
        events = store.events_since(consumed, limit=MAX_SCAN)
        for seq, event in events:
            if seq > through:
                break
            relevant = event.subject_id in refs or self.board.relevant(event, actor)
            if relevant:
                change = self._change(seq, event)
                cost = len(json.dumps(change).encode()) + 2
                if cost > budget // 2 and 'code_anchor' in change:
                    # S4: a heavy code anchor shrinks to its anchor line before the row is given up
                    change['code_anchor'] = change['code_anchor'].split('\n', 1)[0]
                    cost = len(json.dumps(change).encode()) + 2
                if cost > budget // 2:
                    # Never stall on an accepted but unusually large ID/metadata field.
                    change = {'event_id': event.id, 'seq': seq, 'kind': event.kind.value,
                              'object_id': event.id, 'object_type': 'event', 'truncated': True,
                              'action': 'context() to read oversized change; event payload omitted'}
                    cost = len(json.dumps(change).encode()) + 2
                if len(changes) >= limit or size + cost > budget:
                    cut = 'bytes' if size + cost > budget else 'limit'
                    break
                changes.append(change)
                size += cost
            consumed = seq
            anchor = event.id
        else:
            if len(events) < MAX_SCAN:
                consumed = through
        # Global seq includes non-event records. They need no separate event consumption.
        remaining = store.events_since(consumed, limit=1)
        more = bool(remaining and remaining[0][0] <= through)
        if not more:
            consumed = through
        asks = self._asks(actor)
        asks_changed = asks != state['asks']
        metadata = self._metadata(roots)
        metadata_changed = metadata != state['metadata']
        next_state = {**state, 'seq': consumed, 'anchor': anchor, 'through': through if more else None,
                      'metadata': metadata if not more else state['metadata'],
                      'asks': asks if not more else state['asks']}
        result = {'changed': bool(changes) or asks_changed or metadata_changed,
                  'next_cursor': self._encode(next_state), 'has_more': more}
        if metadata_changed:
            result['orientation_changed'] = {'read_ref': {'tool': 'context'},
                                             'action': 'refresh changed ticket metadata/criteria/links/gates/docs'}
        if changes:
            result['changes'] = changes
        if more:  # the page was cut: say why and how to continue (S20)
            why = {'bytes': f'page bounded to EDP8_DELTA_BUDGET_B={budget} bytes',
                   'limit': f'page bounded to limit={limit} changes'}.get(cut, f'scan bounded to {MAX_SCAN} events')
            result['omitted'] = {'why': why, 'continue': 'context_delta(cursor=next_cursor)'}
        if asks_changed:
            result['asks_changed'] = {'read_ref': {'tool': 'inbox'}, 'action': 'read new/resolved/reopened asks'}
        return result

    def _change(self, seq, event):
        b = self.board
        kind = event.kind.value
        row = {'event_id': event.id, 'seq': seq, 'kind': kind, 'object_id': event.subject_id,
               'action': 'read current state'}
        message = b.store.get('message', event.data.get('message', '')) if kind == 'message_sent' else None
        if message is not None:
            row.update(object_type='message', object_id=message.id,
                       read_ref={'tool': 'message_read', 'id': message.id},
                       actor=message.created_by, recipient=message.to,
                       text=message.text[:TEXT_HEAD], truncated=len(message.text) > TEXT_HEAD,
                       **code_row(message))  # S4: the anchor, snippet capped
            return row
        for typ, tool, arg in [('ticket', 'ticket_read', 'ticket_id'), ('doc', 'doc_read', 'id'),
                               ('criterion', 'criterion_query', 'ticket_id'), ('artifact', 'artifact_read', 'id')]:
            obj = b.store.get(typ, event.subject_id)
            if obj is not None:
                id_ = obj.ticket_id if typ == 'criterion' else obj.id
                row.update(object_type=typ, read_ref={'tool': tool, arg: id_})
                if typ == 'doc':
                    row['version'] = obj.version
                return row
        row.update(object_type='event', action='context() to resynchronize unknown/deleted object')
        return row
