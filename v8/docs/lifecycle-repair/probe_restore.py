"""ISOLATED PROOF ONLY. Running this file uses temporary databases, never EDP8_HOME.
No production CLI or live database discovery. Not authorization to run a second live writer.
"""
import json
import sqlite3
import tempfile
import unittest
import uuid
from datetime import datetime, timezone
from pathlib import Path

from edp8.board import Board
from edp8.schemas import (Criterion, Doc, Event, Gate, Message, Participant, Session, Ticket, TicketStatus)
from edp8.store import Store

EPIC = 'epic-44a0576511'
DESIGN = 'design-f716d0d138'
ACTOR = 'architect.epic-44a0576511'
CHILDREN = {
    's-3869d54c5a': 'blocked', 's-64cd665b3a': 'blocked', 's-0e0da66a94': 'blocked',
    's-ec85b2827f': 'signed_off', 's-4983df7e94': 'signed_off',
    's-bb3ab419d2': 'signed_off', 's-c38a764934': 'signed_off',
    's-3a825e253f': 'signed_off',
}


def candidate_restore(conn, *, fail_after_update=False, authorization_message=None, before_image=None):
    """Candidate transaction, to be exercised ONLY on the synthetic fixtures below.

    Restores one status + appends an honestly attributed repair event atomically.
    Does NOT answer the gate, release children, delete history or claim owner identity.
    Live adoption additionally requires maintenance authorization and writer coordination.
    """
    conn.execute('BEGIN IMMEDIATE')
    try:
        def obj(table, key):
            row = conn.execute(f'SELECT body FROM {table} WHERE id=?', (key,)).fetchone()
            if not row:
                raise ValueError(f'missing {table} {key}')
            return json.loads(row[0])
        if (authorization_message is None) != (before_image is None):
            raise ValueError('authorization and before-image must be supplied together')
        if authorization_message is not None:
            if authorization_message != 'm-f5feec237a':
                raise ValueError('this one-time repair requires its exact authorization')
            approval = obj('message', authorization_message)
            owner = obj('participant', approval['created_by'])
            if (owner['type'], owner['role'], approval['ticket_id'], approval['text']) != (
                    'human', 'owner', EPIC, '@architect.epic-44a0576511 yes I authorize'):
                raise ValueError('authorization mismatch')
        epic = obj('ticket', EPIC)
        if (epic['kind'], epic['status'], epic['design_ref'], epic['assignee']) != (
                'epic', 'in_progress', DESIGN, None):
            raise ValueError('epic precondition changed')
        if obj('doc', DESIGN)['version'] != 7:
            raise ValueError('design version changed')
        indexed = conn.execute('SELECT status FROM ticket WHERE id=?', (EPIC,)).fetchone()[0]
        if indexed != epic['status']:
            raise ValueError('index/body mismatch')
        children = [json.loads(r[0]) for r in conn.execute(
            'SELECT body FROM ticket WHERE epic_id=? AND id<>?', (EPIC, EPIC))]
        if {c['id']: c['status'] for c in children} != CHILDREN:
            raise ValueError('descendant set/status changed')
        if any(c['assignee'] is not None for c in children):
            raise ValueError('work assigned')
        criteria = [json.loads(r[0]) for r in conn.execute('SELECT body FROM criterion')]
        if any(c['ticket_id'] in {EPIC, *CHILDREN} and
               (c['verdict'] != 'pending' or c['evidence_ref']) for c in criteria):
            raise ValueError('execution evidence exists')
        sessions = [json.loads(r[0]) for r in conn.execute('SELECT body FROM session')]
        if any(s['ticket_id'] in {EPIC, *CHILDREN} and s['state'] != 'dead'
               and s['participant_id'] != ACTOR for s in sessions):
            raise ValueError('non-architect session exists')
        gate_events = [json.loads(r[0]) for r in conn.execute(
            'SELECT body FROM event WHERE subject_id=? ORDER BY seq', (EPIC,))]
        signoff = [e for e in gate_events if e['kind'] in ('gate_opened', 'gate_answered')
                   and e['data'].get('gate') == 'design_signoff']
        if not signoff or signoff[-1]['kind'] != 'gate_opened':
            raise ValueError('design gate not open')
        before = json.dumps(epic, sort_keys=True)
        if before_image is not None:
            with Path(before_image).open('x', encoding='utf-8') as backup:
                json.dump({'ticket': epic, 'authorization_message': authorization_message,
                           'note': 'Before-image only; not a claim the transaction committed'}, backup, indent=2)
                backup.flush()
                import os
                os.fsync(backup.fileno())
        epic['status'] = 'designed'
        conn.execute('UPDATE ticket SET status=?, body=? WHERE id=? AND status=?',
                     ('designed', json.dumps(epic), EPIC, 'in_progress'))
        if fail_after_update:
            raise RuntimeError('injected transaction failure')
        event = Event(id='ev-' + uuid.uuid4().hex[:10], created_by=ACTOR,
                      created_at=datetime.now(timezone.utc), subject_id=EPIC,
                      kind='status_changed', data={
                          'from': 'in_progress', 'to': 'designed', 'by': ACTOR,
                          'maintenance_repair': True,
                          'reason': ('Owner-authorized one-time pre-execution lifecycle repair'
                                     if authorization_message else 'ISOLATED PROOF: restore pre-execution gate eligibility'),
                          'authorization_message': authorization_message,
                          'approval_not_emitted': True})
        conn.execute("UPDATE seq SET n=n+1 WHERE name='global'")
        seq = conn.execute("SELECT n FROM seq WHERE name='global'").fetchone()[0]
        conn.execute('INSERT INTO event(id,seq,created_at,body,subject_id,kind) VALUES(?,?,?,?,?,?)',
                     (event.id, seq, event.created_at.isoformat(), event.model_dump_json(),
                      EPIC, event.kind.value))
        conn.commit()
        return before, event.id
    except BaseException:
        conn.rollback()
        raise


class RestoreProof(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / 'synthetic.db'
        self.store = Store(self.path)
        self.owner = Participant(id='owner', type='human', role='owner', handle='owner')
        self.store.put('participant', self.owner)
        self.store.put('doc', Doc(id=DESIGN, doc_type='design', title='Synthetic',
                                 body_md='Synthetic design', version=7, owner_role='architect', scope=EPIC))
        self.store.put('ticket', Ticket(id=EPIC, created_by='owner', kind='epic', work_type='feature',
                                       title='Synthetic', words='Unchanged raw request',
                                       epic_id=EPIC, status='in_progress', design_ref=DESIGN))
        for key, status in CHILDREN.items():
            self.store.put('ticket', Ticket(id=key, parent_id=EPIC, epic_id=EPIC, kind='story',
                                           work_type='feature', title='Synthetic', status=status,
                                           design_ref=DESIGN))
            self.store.put('criterion', Criterion(id='c-'+key, ticket_id=key, text='Synthetic check',
                                                 check='command', checked_by='qa'))
        self.store.put('criterion', Criterion(id='c-epic', ticket_id=EPIC, text='Synthetic check',
                                             check='command', checked_by='qa'))
        self.store.put('event', Event(id='ev-open', subject_id=EPIC, kind='gate_opened',
                                     data={'gate': 'design_signoff', 'by': ACTOR}))
        self.store.put('ticket', Ticket(id='epic-sibling', kind='epic', work_type='feature',
                                       title='Sibling untouched'))
        self.conn = sqlite3.connect(self.path)

    def tearDown(self):
        self.conn.close()
        self.store.close()
        self.tmp.cleanup()

    def test_restore_one_row_then_real_owner_gate_api_succeeds(self):
        before = {t.id: t.model_dump_json() for t in self.store.query('ticket')}
        _, event_id = candidate_restore(self.conn)
        after = {t.id: t.model_dump_json() for t in self.store.query('ticket')}
        self.assertEqual([k for k in before if before[k] != after[k]], [EPIC])
        restored = self.store.get('ticket', EPIC)
        self.assertEqual(restored.words, 'Unchanged raw request')
        self.assertEqual(restored.status.value, 'designed')
        board = Board(self.store)
        self.assertTrue(board.open_gates(EPIC, Gate.design_signoff))
        self.assertEqual(self.store.get('event', event_id).created_by, ACTOR)
        board.gate_answer(self.owner, EPIC, Gate.design_signoff, 'Synthetic owner approval v7')
        self.assertFalse(board.open_gates(EPIC, Gate.design_signoff))

    def test_injected_failure_rolls_back_status_and_audit(self):
        old = self.store.get('ticket', EPIC).model_dump_json()
        seq = self.store.max_seq()
        with self.assertRaises(RuntimeError):
            candidate_restore(self.conn, fail_after_update=True)
        self.assertEqual(self.store.get('ticket', EPIC).model_dump_json(), old)
        self.assertEqual(self.store.max_seq(), seq)

    def test_authorized_variant_writes_before_image_and_attributed_audit(self):
        self.store.put('message', Message(id='m-f5feec237a', created_by='owner', ticket_id=EPIC,
                                         kind='note', text='@architect.epic-44a0576511 yes I authorize'))
        backup = Path(self.tmp.name) / 'before.json'
        _, event_id = candidate_restore(self.conn, authorization_message='m-f5feec237a', before_image=backup)
        self.assertEqual(json.loads(backup.read_text())['ticket']['status'], 'in_progress')
        event = self.store.get('event', event_id)
        self.assertEqual(event.data['authorization_message'], 'm-f5feec237a')
        self.assertEqual(event.created_by, ACTOR)
        self.assertEqual(event.kind.value, 'status_changed')

    def test_wrong_authorization_refused(self):
        with self.assertRaisesRegex(ValueError, 'exact authorization'):
            candidate_restore(self.conn, authorization_message='wrong',
                              before_image=Path(self.tmp.name) / 'before.json')
        self.assertEqual(self.store.get('ticket', EPIC).status.value, 'in_progress')

    def test_repeat_refused(self):
        candidate_restore(self.conn)
        with self.assertRaisesRegex(ValueError, 'epic precondition'):
            candidate_restore(self.conn)

    def test_changed_version_refused(self):
        doc = self.store.get('doc', DESIGN)
        doc.version = 8
        self.store.put('doc', doc)
        with self.assertRaisesRegex(ValueError, 'version'):
            candidate_restore(self.conn)

    def test_started_child_refused(self):
        child = self.store.get('ticket', 's-3869d54c5a')
        child.status = TicketStatus.in_progress
        self.store.put('ticket', child)
        with self.assertRaisesRegex(ValueError, 'descendant'):
            candidate_restore(self.conn)

    def test_evidence_refused(self):
        criterion = self.store.get('criterion', 'c-epic')
        criterion.evidence_ref = 'report-something'
        self.store.put('criterion', criterion)
        with self.assertRaisesRegex(ValueError, 'evidence'):
            candidate_restore(self.conn)

    def test_execution_session_refused(self):
        self.store.put('session', Session(id='session-worker', participant_id='engineer.fixture',
                                         ticket_id='s-3869d54c5a', pool_id='synthetic', state='alive'))
        with self.assertRaisesRegex(ValueError, 'session'):
            candidate_restore(self.conn)

    def test_closed_gate_refused(self):
        self.store.put('event', Event(id='ev-closed', subject_id=EPIC, kind='gate_answered',
                                     data={'gate': 'design_signoff', 'by': 'owner'}))
        with self.assertRaisesRegex(ValueError, 'gate not open'):
            candidate_restore(self.conn)

    def test_index_drift_refused(self):
        self.conn.execute('UPDATE ticket SET status=? WHERE id=?', ('ready', EPIC))
        self.conn.commit()
        with self.assertRaisesRegex(ValueError, 'index/body'):
            candidate_restore(self.conn)

    def test_existing_writer_lock_refuses_without_mutation(self):
        other = sqlite3.connect(self.path, timeout=0.05)
        self.conn.execute('BEGIN IMMEDIATE')
        try:
            with self.assertRaises(sqlite3.OperationalError):
                candidate_restore(other)
        finally:
            other.close()
            self.conn.rollback()
        self.assertEqual(self.store.get('ticket', EPIC).status.value, 'in_progress')

    def test_sibling_write_after_repair_remains_possible(self):
        candidate_restore(self.conn)
        sibling = self.store.get('ticket', 'epic-sibling')
        sibling.description = 'Still writable'
        self.store.put('ticket', sibling)
        self.assertEqual(self.store.get('ticket', sibling.id).description, 'Still writable')


if __name__ == '__main__':
    unittest.main()
