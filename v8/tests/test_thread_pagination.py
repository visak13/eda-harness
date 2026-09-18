"""Owner regression: totals are not the newest-100 window size."""
import pytest
from edp8.board import Board
from edp8.store import Store
from edp8.schemas import Role, TicketKind, WorkType, MessageKind
from edp8 import views

@pytest.fixture
def thread():
    b = Board(Store(":memory:"))
    owner = b.participant_create("human", Role.owner, "owner", id_="owner")
    t = b.ticket_create(owner, kind=TicketKind.epic, work_type=WorkType.feature, title="Long conversation")
    messages = [b.message_send(owner, ticket_id=t.id, to=None, kind=MessageKind.note, text=f"Message {i}") for i in range(235)]
    return b, owner, t, messages

def test_authenticated_api_pagination(thread, monkeypatch, tmp_path):
    import json
    from fastapi.testclient import TestClient
    from edp8.service import create_app
    b, _, t, _ = thread
    tokens = tmp_path / "tokens.json"
    tokens.write_text(json.dumps({"owner": "fixture-secret", "agents": {}}))
    monkeypatch.setenv("EDP8_TOKENS", str(tokens))
    with TestClient(create_app(b, admin_token="t")) as client:
        headers = {"X-Participant": "owner", "X-Token": "fixture-secret"}
        route = f"/v1/tickets/{t.id}/thread"
        assert client.get(route, headers={"X-Participant": "owner"}).status_code == 401
        first = client.get(route, headers=headers).json()["value"]
        assert first["thread_total"] == 235
        second = client.get(route, params={"before": first["thread_before"]}, headers=headers).json()["value"]
        assert len(second["thread"]) == 100
        assert not {m["id"] for m in first["thread"]} & {m["id"] for m in second["thread"]}
        assert client.get(route, params={"before": -1}, headers=headers).status_code == 422
        assert client.get(route, params={"before": "oops"}, headers=headers).status_code == 422
        assert client.get(route, params={"before": 10**40}, headers=headers).status_code == 422


def test_total_exceeds_even_the_stores_default_500_limit(thread):
    b, owner, t, _ = thread
    for i in range(366):
        b.message_send(owner, ticket_id=t.id, to=None, kind=MessageKind.note, text=str(i))
    page = views.thread_page(b, t.id)
    assert page["thread_total"] == 601
    assert len(page["thread"]) == 100


def test_total_is_not_bounded_page_size(thread):
    b, _, t, messages = thread
    for page in (views.epic_page(b, t.id), views.ticket_page(b, t.id)):
        assert len(page["thread"]) == 100
        assert page["thread_total"] == 235
        assert [m["id"] for m in page["thread"]] == [m.id for m in messages[-100:]]

def test_cursor_pages_deep_link_and_concurrent_arrival(thread):
    b, owner, t, messages = thread
    page = views.thread_page(b, t.id, include=messages[0].id)
    assert len(page["thread"]) == 101
    first_cursor = page["thread_before"]
    b.message_send(owner, ticket_id=t.id, to=None, kind=MessageKind.note, text="Arrived after first page")
    older = views.thread_page(b, t.id, before=first_cursor)
    assert older["thread_total"] == 236
    assert [m["id"] for m in older["thread"]] == [m.id for m in messages[35:135]]
    oldest = views.thread_page(b, t.id, before=older["thread_before"])
    assert [m["id"] for m in oldest["thread"]] == [m.id for m in messages[:35]]
    assert oldest["thread_before"] is None
    other = b.ticket_create(owner, kind=TicketKind.epic, work_type=WorkType.feature, title="Other")
    assert views.thread_page(b, other.id, include=messages[0].id)["thread"] == []
