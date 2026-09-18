"""S5 selectors: characterize inbox/owner authority, then pin minimal delivery API."""
import pytest
from fastapi.testclient import TestClient
from edp8.board import Board
from edp8.notifications import attention
from edp8.schemas import Role, TicketKind, WorkType, Gate, MessageKind
from edp8.service import create_app
from edp8.store import Store


@pytest.fixture
def rig(monkeypatch):
    from edp8 import broker_adapter
    monkeypatch.setattr(broker_adapter, "publish", lambda *a, **kw: True)
    b = Board(Store())
    owner = b.participant_create("human", Role.owner, "owner")
    other = b.participant_create("human", Role.owner, "other")
    arch = b.participant_create("agent", Role.architect, "arch")
    epic = b.ticket_create(owner, kind=TicketKind.epic, work_type=WorkType.feature, title="Private title")
    return b, owner, other, arch, epic


def send(rig, kind=MessageKind.question, to=None, reply_to=None):
    b, owner, _, arch, epic = rig
    return b.message_send(arch, ticket_id=epic.id, kind=kind, text="PRIVATE BODY", to=to or owner.id, reply_to=reply_to)


def test_baseline_no_backlog_and_server_recipient_filter(rig):
    b, owner, other, _, _ = rig
    send(rig)
    baseline = attention(b, owner)
    assert baseline["requests"] == []
    send(rig, MessageKind.note)
    send(rig, MessageKind.steer)
    send(rig, to=other.id)
    message = send(rig)
    value = attention(b, owner, since=baseline["cursor"])
    assert len(value["requests"]) == 1
    row = value["requests"][0]
    assert row["url"].endswith("#" + message.id)
    assert "PRIVATE" not in str(value) and "text" not in str(value)
    assert row["request"].startswith("ev-")
    assert attention(b, other, request=row["request"])["requests"] == []
    assert attention(b, owner, request=row["request"])["requests"] == [row]
    assert attention(b, owner, since=value["cursor"])["requests"] == []


def test_click_revalidates_answered_and_gate_owner(rig):
    b, owner, other, _, epic = rig
    baseline = attention(b, owner)["cursor"]
    message = send(rig)
    gate = b.gate_open(epic.id, Gate.demo)
    rows = attention(b, owner, since=baseline)["requests"]
    assert len(rows) == 2
    assert attention(b, other, request=gate.id)["requests"] == []
    send(rig, MessageKind.answer, reply_to=message.id)
    assert attention(b, owner, request=rows[0]["request"])["requests"] == []
    assert attention(b, owner, request="ev-missing")["requests"] == []
    b.gate_answer(owner, epic.id, Gate.demo, "approved")
    assert attention(b, owner, request=gate.id)["requests"] == []


def test_pagination_keeps_unrelated_burst_from_dropping_request(rig):
    b, owner, _, _, _ = rig
    cursor = attention(b, owner)["cursor"]
    for _ in range(205):
        send(rig, MessageKind.note)
    send(rig)
    first = attention(b, owner, since=cursor)
    assert first["requests"] == []
    assert len(attention(b, owner, since=first["cursor"])["requests"]) == 1


def test_endpoint_auth_and_minimal_shape(rig, tmp_path, monkeypatch):
    import json
    b, owner, _, _, _ = rig
    tokens = tmp_path / 'tokens.json'
    tokens.write_text(json.dumps({'owner': 'secret'}), encoding='utf-8')
    monkeypatch.setenv('EDP8_TOKENS', str(tokens))
    client = TestClient(create_app(b))
    assert client.get('/v1/me/notifications').status_code == 401
    assert client.get('/v1/me/notifications', headers={'X-Participant': owner.id}).status_code == 401
    response = client.get('/v1/me/notifications', headers={'X-Participant': owner.id, 'X-Token': 'secret'})
    assert response.json()['ok']
    assert set(response.json()['value']) == {'participant', 'cursor', 'requests'}
    assert 'secret' not in response.text
