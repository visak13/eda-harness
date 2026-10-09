"""s-0b8d2e5393 (design-63db8a7d42 item K, owner m-4b4bd9b35e): each role's tools come from a per-role table built from
what the role must do (bundles.ROLE_BUNDLES, with the reason for every tool in bundles._TOOL_WHY). The past-usage
pruning (S20 `_S20_UNUSED`) is gone: it had taken doc_edit and artifact_upload from the sme and artifact_upload from qa.
This test pins every list, so a change to a role's tools is a change to this file too.
"""
from __future__ import annotations

import pytest

from edp8 import bundles
from edp8.bundles import ALL_TOOLS, ROLE_BUNDLES, tools_for_role

EXPECTED = {
    'owner': {
        'board', 'close', 'context', 'context_delta', 'criterion_query', 'criterion_update', 'describe',
        'describe_objects', 'doc_query', 'doc_read', 'events_query', 'find', 'gate_answer', 'gates',
        'get_guide', 'harvest_cost', 'lookup', 'message_query', 'message_read', 'message_send', 'pain',
        'participants', 'preflight', 'reap', 'record_claim', 'record_decision', 'resume', 'resume_self',
        'retire_lesson', 'service_status', 'session_query', 'spawn', 'subscribe', 'teammate', 'ticket_create',
        'ticket_query', 'ticket_read', 'ticket_update', 'whoami', 'workflow',
    },
    'architect': {
        'artifact_create', 'artifact_upload', 'board', 'context', 'context_delta', 'criterion_create',
        'criterion_query', 'criterion_update', 'describe', 'describe_objects', 'doc_create', 'doc_edit',
        'doc_query', 'doc_read', 'doc_update', 'events_query', 'find', 'gate_open', 'gates', 'get_guide',
        'inbox', 'link_create', 'link_delete', 'link_query', 'lookup', 'message_query', 'message_read',
        'message_send', 'pain', 'participants', 'preflight', 'reap', 'record_claim', 'record_decision',
        'record_lesson', 'record_status', 'requirement_link', 'requirements', 'resume', 'resume_self',
        'retire_lesson', 'service_status', 'session_query', 'set_binding', 'spawn', 'subscribe',
        'ticket_create', 'ticket_query', 'ticket_read', 'ticket_update', 'whoami',
    },
    'sme': {
        'artifact_upload', 'close_self', 'context', 'context_delta', 'criterion_query', 'criterion_update',
        'describe', 'describe_objects', 'doc_create', 'doc_edit', 'doc_query', 'doc_read', 'doc_update',
        'find', 'get_guide', 'inbox', 'link_create', 'link_query', 'lookup', 'message_query', 'message_read',
        'message_send', 'pain', 'participants', 'preflight', 'record_claim', 'record_decision',
        'record_lesson', 'record_status', 'resume_self', 'subscribe', 'ticket_query', 'ticket_read',
        'ticket_update', 'topic_propose', 'topic_research', 'whoami',
    },
    'engineer': {
        'artifact_create', 'artifact_read', 'artifact_upload', 'close_self', 'context', 'context_delta',
        'criterion_create', 'criterion_query', 'criterion_update', 'describe', 'describe_objects',
        'doc_create', 'doc_edit', 'doc_query', 'doc_read', 'doc_update', 'find', 'gate_open', 'get_guide',
        'inbox', 'link_create', 'link_query', 'lookup', 'message_query', 'message_read', 'message_send',
        'pain', 'participants', 'preflight', 'record_claim', 'record_decision', 'record_lesson',
        'record_status', 'resume_self', 'subscribe', 'ticket_create', 'ticket_query', 'ticket_read',
        'ticket_update', 'whoami', 'withdraw_decision',
    },
    'adversary': {
        'artifact_create', 'artifact_read', 'artifact_upload', 'close_self', 'context', 'context_delta',
        'criterion_create', 'criterion_query', 'criterion_update', 'describe', 'describe_objects',
        'doc_create', 'doc_edit', 'doc_query', 'doc_read', 'doc_update', 'find', 'gate_open', 'gates',
        'get_guide', 'inbox', 'link_create', 'link_query', 'lookup', 'message_query', 'message_read',
        'message_send', 'pain', 'participants', 'preflight', 'record_claim', 'record_decision',
        'record_lesson', 'record_status', 'resume_self', 'subscribe', 'ticket_create', 'ticket_query',
        'ticket_read', 'ticket_update', 'whoami',
    },
    'qa': {
        'artifact_read', 'artifact_upload', 'board', 'close_self', 'context', 'context_delta',
        'criterion_query', 'criterion_update', 'describe', 'describe_objects', 'doc_create', 'doc_edit',
        'doc_read', 'doc_update', 'find', 'gates', 'get_guide', 'harvest_cost', 'inbox', 'link_create',
        'lookup', 'message_query', 'message_read', 'message_send', 'pain', 'participants', 'preflight',
        'record_claim', 'record_decision', 'record_lesson', 'record_status', 'requirements', 'resume_self',
        'subscribe', 'ticket_read', 'ticket_update', 'whoami',
    },
    'doctor': {
        'board', 'close_self', 'context', 'context_delta', 'criterion_query', 'describe', 'describe_objects',
        'doc_query', 'doc_read', 'doctor_dead_mail', 'doctor_feed_lag', 'doctor_health', 'doctor_logs',
        'doctor_pains', 'doctor_pool', 'events_query', 'find', 'gates', 'get_guide', 'inbox', 'lookup',
        'message_query', 'message_read', 'message_send', 'pain', 'participants', 'preflight', 'propose_fix',
        'record_status', 'resume_self', 'service_status', 'subscribe', 'ticket_query', 'ticket_read',
        'whoami', 'why_stuck', 'workflow_check',
    },
}


@pytest.mark.parametrize("role", sorted(EXPECTED))
def test_each_roles_tool_list_is_pinned(role):
    assert set(ROLE_BUNDLES[role]) == EXPECTED[role]
    assert len(ROLE_BUNDLES[role]) == len(set(ROLE_BUNDLES[role])), "a tool is listed twice"
    assert {t.name for t in tools_for_role(role)} == EXPECTED[role]


def test_every_role_has_a_table_and_no_other_role_has_a_list():
    assert set(ROLE_BUNDLES) == set(EXPECTED) == set(bundles._ROLE_JOB)


def test_the_sme_can_edit_docs_and_upload_and_qa_can_upload():
    assert {"doc_edit", "artifact_upload"} <= set(ROLE_BUNDLES["sme"])
    assert "artifact_upload" in ROLE_BUNDLES["qa"]


def test_the_usage_based_pruning_is_gone():
    assert not hasattr(bundles, "_S20_UNUSED")


@pytest.mark.parametrize("role", sorted(EXPECTED))
def test_every_listed_tool_exists_and_says_why(role):
    doctor_only = {t.name for t in bundles.DOCTOR_TOOLS}
    for name in ROLE_BUNDLES[role]:
        assert name in ALL_TOOLS, name
        assert name in bundles._TOOL_WHY or name in doctor_only, f"{role}: {name} has no reason in _TOOL_WHY"


@pytest.mark.parametrize("role", sorted(EXPECTED))
def test_the_identity_tools_lead_every_list(role):
    assert ROLE_BUNDLES[role][:len(bundles._IDENTITY)] == bundles._IDENTITY


@pytest.mark.parametrize("role", ["sme", "engineer", "adversary", "qa", "doctor"])
def test_a_doing_seat_ends_inbox_status_close(role):
    assert ROLE_BUNDLES[role][-3:] == ["inbox", "record_status", "close_self"]


@pytest.mark.parametrize("role", ["owner", "architect"])
def test_the_owner_and_architect_never_close_themselves(role):
    assert "close_self" not in ROLE_BUNDLES[role]


@pytest.mark.parametrize("role", ["owner", "architect", "sme", "engineer", "adversary", "qa"])
def test_every_writing_role_records_and_recalls(role):
    assert {"record_decision", "record_claim", "lookup"} <= set(ROLE_BUNDLES[role])
