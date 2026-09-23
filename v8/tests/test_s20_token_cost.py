"""S20 token-cost rework (s-b123a91d3f): byte caps on the per-heartbeat payloads and the per-role
tool surface.

c-88e0a8dac4: context_delta() pages and feed_driver lines are byte-capped with a fetch hint on the
cut, and both caps are env-overridable like EDP8_CONTEXT_BUDGET_B.
c-3158a4f2c1: every tool keeps "When to call", its enum list and the Returns line (the full check is
test_tool_descriptions.py::test_description_has_four_parts; the advertised schema keeps every enum).
c-a268f6ab90: each role's tool surface is <= 50% of the audit's bytes and keeps every tool it invoked.
"""
import json

import pytest
from test_context_delta_s7 import ENG, delta, send, snapshot
from test_context_tools import H, board, client, rig  # noqa: F401 — fixtures

from edp8 import feed_driver
from edp8.bundles import ALL_TOOLS, ROLE_BUNDLES, enum_fields, tools_for_role


# ----------------------------------------------------------------------------- context_delta cap
def test_delta_over_a_200_message_window_is_capped_with_a_continue_hint(client, rig):
    base = snapshot(client)['cursor']
    for i in range(200):
        send(client, rig, f'msg {i} ' + 'Y' * 600)
    out = delta(client, base, limit=100)
    assert len(json.dumps(out).encode()) <= 12_000
    v = out['value']
    assert v['has_more'] and v['omitted']['continue'] == 'context_delta(cursor=next_cursor)'
    assert 'EDP8_DELTA_BUDGET_B=12000' in v['omitted']['why']
    assert all(c['read_ref']['tool'] == 'message_read' and c['truncated'] for c in v['changes'])
    seen, page = len(v['changes']), v
    while page['has_more']:  # the cut loses nothing: every message arrives across the pages
        page = delta(client, page['next_cursor'], limit=100)['value']
        seen += len(page.get('changes', []))
    assert seen == 200


def test_delta_cap_is_env_overridable(client, rig, monkeypatch):
    monkeypatch.setenv('EDP8_DELTA_BUDGET_B', '6000')
    base = snapshot(client)['cursor']
    for i in range(40):
        send(client, rig, 'Z' * 600)
    out = delta(client, base, limit=100)
    assert len(json.dumps(out).encode()) <= 6_000
    assert 'EDP8_DELTA_BUDGET_B=6000' in out['value']['omitted']['why']


def test_small_delta_carries_no_receipt(client, rig):
    base = snapshot(client)['cursor']
    send(client, rig, 'one')
    v = delta(client, base)['value']
    assert v['changed'] and not v['has_more'] and 'omitted' not in v


# ----------------------------------------------------------------------------- feed_driver cap
def _msg_event(text):
    return {'event': {'seq': 12846, 'why': 'addressed to you', 'id': 'ev-1', 'subject_id': 's-1',
                      'kind': 'message_sent', 'data': {'message': 'm-176136b902', 'kind': 'steer', 'text': text}}}


def test_feed_event_with_a_30kb_body_is_capped_with_a_fetch_hint():
    out = feed_driver.cap_line(_msg_event('x' * 30_000))
    assert len(json.dumps(out).encode()) <= 2_000
    assert out['omitted']['fetch'] == "message_read(id='m-176136b902')"
    assert out['event']['data']['text'].endswith('chars]')
    assert out['event']['seq'] == 12846 and out['event']['kind'] == 'message_sent'  # structure survives


def test_broker_line_with_multibyte_30kb_body_is_capped():
    line = {'broker_msg': {'msg_id': 'u', 'from': 'architect.e', 'kind': 'steer',
                           'body': {'ticket_id': 's-1', 'text': 'é—' * 15_000}}}
    out = feed_driver.cap_line(line)
    assert len(json.dumps(out).encode()) <= 2_000
    assert "message_query(ticket_id='s-1')" in out['omitted']['fetch']


def test_feed_cap_is_env_overridable_and_small_lines_pass_through(monkeypatch, capsys):
    small = _msg_event('short')
    assert feed_driver.cap_line(small) is small
    monkeypatch.setenv('EDP8_FEED_EVENT_B', '900')
    feed_driver._print(_msg_event('y' * 5_000))
    line = capsys.readouterr().out.strip()
    assert len(line.encode()) <= 900 and 'EDP8_FEED_EVENT_B=900' in line


# ----------------------------------------------------------------------------- tool surface
_AUDIT_BEFORE = {'architect': 52_174, 'engineer': 48_457, 'adversary': 48_457, 'qa': 44_823,
                 'sme': 39_078, 'owner': 37_337}


def _surface_bytes(role):
    return sum(len(t.name.encode()) + len(t.description.encode())
               + len(json.dumps(t.input_schema, ensure_ascii=False).encode()) for t in tools_for_role(role))


@pytest.mark.parametrize('role', sorted(_AUDIT_BEFORE))
def test_role_tool_surface_is_at_most_half_the_audit(role):
    assert _surface_bytes(role) <= _AUDIT_BEFORE[role] // 2


@pytest.mark.parametrize('name', sorted(ALL_TOOLS))
def test_advertised_schema_keeps_every_enum_and_required_field(name):
    tool = ALL_TOOLS[name]
    schema = tool.input_schema
    props = schema.get('properties', {})
    for field, values in enum_fields(tool.args_model).items():
        node = props[field]
        got = node.get('enum') or [v for alt in node.get('anyOf', []) for v in alt.get('enum', [])]
        assert got == values, (name, field)
    assert schema.get('required', []) == tool.args_model.model_json_schema().get('required', [])
    assert '"title"' not in json.dumps(schema) or 'title' in props  # titles gone (a field may be named title)


def test_invoked_tools_stay_in_their_role():
    """Every tool a role invoked in the 30-day transcript scan (report table) is still in its bundle."""
    invoked = {
        'architect': {'message_send', 'criterion_create', 'context', 'ticket_update', 'message_query', 'link_create',
                      'message_read', 'ticket_create', 'doc_read', 'criterion_update', 'events_query', 'inbox', 'spawn',
                      'ticket_read', 'criterion_query', 'consult', 'find', 'resume_self', 'doc_create',
                      'consult_status', 'ticket_query', 'gates', 'participants', 'whoami', 'board', 'doc_query',
                      'set_binding', 'subscribe', 'session_query', 'doc_update', 'preflight', 'record_status',
                      'get_guide', 'describe', 'gate_open', 'record_decision', 'artifact_create', 'link_query',
                      'artifact_upload', 'link_delete', 'resume', 'reap', 'lookup', 'doc_edit', 'record_claim'},
        'engineer': {'message_send', 'criterion_update', 'context', 'ticket_update', 'message_read', 'doc_read',
                     'doc_create', 'message_query', 'ticket_create', 'link_create', 'inbox', 'context_delta',
                     'consult_status', 'whoami', 'consult', 'subscribe', 'doc_edit', 'record_status',
                     'assemble_ruleset', 'describe', 'doc_update', 'get_guide', 'artifact_create', 'criterion_query',
                     'close_self', 'ticket_read', 'participants', 'find', 'criterion_create', 'artifact_upload',
                     'lookup', 'doc_query', 'ticket_query', 'artifact_read', 'withdraw_decision', 'link_query',
                     'record_claim', 'describe_objects', 'record_decision', 'resume_self'},
        'qa': {'message_send', 'criterion_update', 'message_read', 'doc_read', 'inbox', 'context', 'consult_status',
               'message_query', 'whoami', 'subscribe', 'get_guide', 'record_status', 'criterion_query', 'doc_edit',
               'context_delta', 'doc_create', 'consult', 'link_create', 'assemble_ruleset', 'close_self',
               'ticket_read', 'lookup', 'ticket_update', 'doc_update', 'gates', 'describe', 'find', 'participants',
               'artifact_read', 'board', 'preflight'},
        'sme': {'message_send', 'context', 'criterion_update', 'link_create', 'doc_read', 'doc_update',
                'message_query', 'whoami', 'subscribe', 'describe', 'doc_create', 'criterion_query', 'inbox',
                'assemble_ruleset', 'record_status', 'message_read', 'doc_query', 'get_guide', 'participants',
                'ticket_update', 'ticket_read', 'close_self', 'link_query', 'ticket_query'},
        'owner': {'spawn', 'message_send', 'message_query', 'message_read', 'ticket_read', 'preflight',
                  'session_query', 'doc_read', 'context', 'criterion_update', 'whoami', 'board', 'ticket_query',
                  'subscribe', 'criterion_query', 'gate_answer', 'ticket_create', 'find', 'ticket_update',
                  'participants', 'gates', 'reap', 'events_query', 'get_guide', 'resume', 'doc_query', 'close'},
        'adversary': {'message_query', 'message_send', 'ticket_update', 'context', 'doc_read', 'participants',
                      'criterion_update', 'whoami', 'subscribe', 'assemble_ruleset', 'ticket_read', 'consult',
                      'doc_create', 'link_create', 'gate_open', 'gates', 'doc_update'},
    }
    for role, names in invoked.items():
        missing = names - set(ROLE_BUNDLES[role])
        assert not missing, (role, missing)
