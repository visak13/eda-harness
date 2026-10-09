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


# S23 re-baseline (architect ruling m-fbd6ae40d3), tightened by e0cec S9 (s-8ca20e8543): the roles that still carry a
# measured shortfall, in bytes, after the S3-S6 terms were removed for real (the Objects/Skills clause left every
# description with the architect's approval, m-1fc3764b91; paging/enum prose and tautological arg descriptions went).
# architect/sme/owner keep the facts the owner's no-loss steer (m-891b9f42bd) holds in descriptions; the owner also
# the five framework tools (pain, workflow, teammate, service_status, harvest_cost) that replace shell workarounds.
# S17 (architect ruling m-04ea10d572 on m-d6452d2753): architect +140 = the measured 135-byte remainder of the
# "(/doc-write)" clause on doc_create/doc_edit/doc_update, doc_update's `layout` arg, doc_read's `include_children`
# arg (m-8c4f0d64cb) and the pre-S23 facts doc_edit/doc_read keep (test_tool_info_parity), rounded up to 10; the
# other roles absorb it. Ruling m-c6cdb0602c (doc_read: no `all`; its description says page 1 holds every obligation
# and sections are read by heading): architect +20 and owner +20 = the measured 19- and 15-byte remainders, rounded up.
# S13 F9 (architect ruling on t-dac2a14caf: the doc_read description is advisory, page 1 is the writer's unchecked
# summary): architect +20 and owner +20 = the measured 20- and 16-byte remainders, rounded up (m-04ea10d572 rule).
# S13 F8 (compact ticket_read default; the tool names its compact read and `more`): architect +20 and owner +10 = the
# measured 14- and 10-byte remainders, rounded up (m-04ea10d572 rule).
# note-e6ddb85977 §3 (s-4bf4ffea8a): doc_read's "head first, then whole or sections (/doc-read)" clause and its `fresh` arg:
# architect +80 and owner +80 = the measured 72- and 78-byte remainders, rounded up (m-04ea10d572 rule).
# astra F5 (report-08d356b0f8, architect m-bbd09fc118): describe's returns say related_skills is an index and the card's
# SKILLS line binds; the narrower spawn and topic_propose enums (F2) absorb part of it: architect +30
# and owner +50 = the measured 24- and 42-byte remainders (surface 27004 and 20540), rounded up (m-04ea10d572 rule).
# Owner m-b9f93cddf0 (the sme is for research): ticket_update's `work_type` retypes a story so its pending criteria
# follow the checker: architect +150 and owner +150 = the measured 142- and 140-byte remainders (surface 27152 and
# 20688), rounded up (m-04ea10d572 rule).
# e0cec K (s-0b8d2e5393, design-63db8a7d42): the per-role table gives the sme back doc_edit and artifact_upload, which
# S20 pruned by past use, and close_self now says it never refuses: sme +980 = the measured 922- and 972-byte remainders (surface 21012), rounded up (m-04ea10d572 rule).
# s-0b8d2e5393 J: ticket_create's `cap_lift_message` arg: architect +50 and owner +50 = the measured 48- and 46-byte
# remainders (surface 27208 and 20744), rounded up (m-04ea10d572 rule).
# Rebased on main 3a462867: main's own doc_edit description growth left the architect 351 bytes over before this story; the figures
# above add this story's 96 (architect) and the sme's rebased measure (surface 21533), rounded up. The doc_edit fact loss in
# test_tool_info_parity[doc_edit] is main's too and is not touched here.
_S23_REBASELINE = {'architect': 1_530, 'sme': 2_000, 'owner': 2_090}


@pytest.mark.parametrize('role', sorted(_AUDIT_BEFORE))
def test_role_tool_surface_is_at_most_half_the_audit(role):
    assert _surface_bytes(role) <= _AUDIT_BEFORE[role] // 2 + _S23_REBASELINE.get(role, 0)


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
    """Every tool a role invoked in the 30-day transcript scan (report table) is still in its bundle. S17 removed
    the ruleset tool on design-f39cf0db7d decision 5; it left the scan's sets with it."""
    invoked = {
        'architect': {'message_send', 'criterion_create', 'context', 'ticket_update', 'message_query', 'link_create',
                      'message_read', 'ticket_create', 'doc_read', 'criterion_update', 'events_query', 'inbox', 'spawn',
                      'ticket_read', 'criterion_query', 'find', 'resume_self', 'doc_create',
                      'ticket_query', 'gates', 'participants', 'whoami', 'board', 'doc_query',
                      'set_binding', 'subscribe', 'session_query', 'doc_update', 'preflight', 'record_status',
                      'get_guide', 'describe', 'gate_open', 'record_decision', 'artifact_create', 'link_query',
                      'artifact_upload', 'link_delete', 'resume', 'reap', 'lookup', 'doc_edit', 'record_claim'},
        'engineer': {'message_send', 'criterion_update', 'context', 'ticket_update', 'message_read', 'doc_read',
                     'doc_create', 'message_query', 'ticket_create', 'link_create', 'inbox', 'context_delta',
                     'whoami', 'subscribe', 'doc_edit', 'record_status',
                     'describe', 'doc_update', 'get_guide', 'artifact_create', 'criterion_query',
                     'close_self', 'ticket_read', 'participants', 'find', 'criterion_create', 'artifact_upload',
                     'lookup', 'doc_query', 'ticket_query', 'artifact_read', 'withdraw_decision', 'link_query',
                     'record_claim', 'describe_objects', 'record_decision', 'resume_self'},
        'qa': {'message_send', 'criterion_update', 'message_read', 'doc_read', 'inbox', 'context',
               'message_query', 'whoami', 'subscribe', 'get_guide', 'record_status', 'criterion_query', 'doc_edit',
               'context_delta', 'doc_create', 'link_create', 'close_self',
               'ticket_read', 'lookup', 'ticket_update', 'doc_update', 'gates', 'describe', 'find', 'participants',
               'artifact_read', 'board', 'preflight'},
        'sme': {'message_send', 'context', 'criterion_update', 'link_create', 'doc_read', 'doc_update',
                'message_query', 'whoami', 'subscribe', 'describe', 'doc_create', 'criterion_query', 'inbox',
                'record_status', 'message_read', 'doc_query', 'get_guide', 'participants',
                'ticket_update', 'ticket_read', 'close_self', 'link_query', 'ticket_query'},
        'owner': {'spawn', 'message_send', 'message_query', 'message_read', 'ticket_read', 'preflight',
                  'session_query', 'doc_read', 'context', 'criterion_update', 'whoami', 'board', 'ticket_query',
                  'subscribe', 'criterion_query', 'gate_answer', 'ticket_create', 'find', 'ticket_update',
                  'participants', 'gates', 'reap', 'events_query', 'get_guide', 'resume', 'doc_query', 'close'},
        'adversary': {'message_query', 'message_send', 'ticket_update', 'context', 'doc_read', 'participants',
                      'criterion_update', 'whoami', 'subscribe', 'ticket_read',
                      'doc_create', 'link_create', 'gate_open', 'gates', 'doc_update'},
    }
    for role, names in invoked.items():
        missing = names - set(ROLE_BUNDLES[role])
        assert not missing, (role, missing)
