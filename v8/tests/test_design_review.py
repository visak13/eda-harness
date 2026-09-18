"""S3 typed review: exact version, non-accepting feedback, retries, races and rollback."""
from concurrent.futures import ThreadPoolExecutor

import pytest
from fastapi.testclient import TestClient
from edp8.board import Board, BoardError
from edp8.design_review import ReviewDecision, DocumentComment, decide, comment
from edp8.schemas import Role, TicketKind, WorkType, DocType, Gate, TicketStatus, Check, EventKind, ArtifactForm
from edp8.contextual_work import contextual_work
from edp8.service import create_app
from edp8.store import Store


@pytest.fixture
def rig():
    board = Board(Store())
    owner = board.participant_create("human", Role.owner, "owner")
    architect = board.participant_create("agent", Role.architect, "architect")
    other = board.participant_create("human", Role.owner, "other")
    epic = board.ticket_create(owner, kind=TicketKind.epic, work_type=WorkType.feature, title="Test")
    doc = board.doc_create(architect, doc_type=DocType.design, title="Design", body_md="v1", scope=epic.id)
    board.criterion_create(architect, ticket_id=epic.id, text="works", check=Check.command)
    board.ticket_update(architect, epic.id, design_ref=doc.id)
    gate = board.gate_open(epic.id, Gate.design_signoff)
    body = ReviewDecision(ticket_id=epic.id, gate_event_id=gate.id, decision="approve", design_ref=doc.id,
                          reviewed_version=1, idempotency_key="action-1")
    return board, owner, architect, other, body


def test_approval_audits_exact_version_and_duplicate_is_one_acceptance(rig):
    b, owner, _, _, body = rig
    first, fresh = decide(b, owner, body)
    assert fresh and decide(b, owner, body) == (first, False)
    assert b.ticket(body.ticket_id).status == TicketStatus.signed_off
    ev = b.store.get("event", first["event_id"])
    assert ev.data["reviewed_version"] == 1 and ev.data["gate_event_id"] == body.gate_event_id
    assert len(b.store.query("event", {"kind": EventKind.gate_answered})) == 1


def test_request_changes_and_comments_never_accept(rig):
    b, owner, _, _, body = rig
    request = body.model_copy(update={"decision": "request_changes", "feedback": "Please clarify"})
    result, _ = decide(b, owner, request)
    msg = b.store.get("message", result["message_id"])
    assert msg.document_context.reviewed_version == 1
    assert msg.to and msg.kind.value == "steer"
    assert b.ticket(body.ticket_id).status == TicketStatus.designed
    assert b.open_gates(body.ticket_id)
    assert not b.store.query("event", {"kind": EventKind.gate_answered})
    c = DocumentComment(ticket_id=body.ticket_id, design_ref=body.design_ref, reviewed_version=1,
                        text="A comment", idempotency_key="comment-1")
    assert comment(b, owner, c)[1]
    assert not comment(b, owner, c)[1]
    assert b.open_gates(body.ticket_id)


def test_unauthorized_stale_unrelated_and_key_reuse(rig):
    b, owner, architect, other, body = rig
    for actor in (architect, other):
        with pytest.raises(BoardError, match="owner"):
            decide(b, actor, body)
    b.doc_update(architect, body.design_ref, body_md="v2")
    with pytest.raises(BoardError, match="changed"):
        decide(b, owner, body)
    body = body.model_copy(update={"reviewed_version": 2})
    decide(b, owner, body)
    with pytest.raises(BoardError, match="idempotency"):
        decide(b, owner, body.model_copy(update={"feedback": "different"}))


def test_racing_approval_accepts_once(rig):
    b, owner, _, _, body = rig
    def run(n):
        try:
            return decide(b, owner, body.model_copy(update={"idempotency_key": str(n)}))[1]
        except BoardError:
            return False
    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sum(pool.map(run, range(2))) == 1


def test_atomic_rollback_does_not_publish_or_keep_acceptance(rig, monkeypatch):
    b, owner, _, _, body = rig
    before = b.store.max_seq()
    published = []
    monkeypatch.setattr(b, "_fanout", published.append)
    original = b.store.put
    def put(kind, obj):
        if obj.id.startswith("review-"):
            raise RuntimeError("simulated disk failure")
        return original(kind, obj)
    monkeypatch.setattr(b.store, "put", put)
    with pytest.raises(RuntimeError):
        decide(b, owner, body)
    assert b.store.max_seq() == before
    assert b.open_gates(body.ticket_id)
    assert b.ticket(body.ticket_id).status == TicketStatus.designed
    assert published == []


def test_feedback_attachments_ownership_and_atomic_rollback(rig, monkeypatch):
    b, owner, _, other, body = rig
    own = b.artifact_upload(owner, form=ArtifactForm.image, content_type="image/png")
    foreign = b.artifact_upload(other, form=ArtifactForm.image, content_type="image/png")
    request = body.model_copy(update={"decision": "request_changes", "feedback": "See image", "artifacts": [own.id, foreign.id]})
    with pytest.raises(BoardError, match="uploader"):
        decide(b, owner, request)
    assert b.store.get("artifact", own.id).staged
    request = request.model_copy(update={"artifacts": [own.id]})
    original = b.message_send
    monkeypatch.setattr(b, "message_send", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("write failed")))
    with pytest.raises(RuntimeError):
        decide(b, owner, request)
    assert b.store.get("artifact", own.id).staged
    assert not b.store.query("link", {"to_id": own.id})
    monkeypatch.setattr(b, "message_send", original)
    decide(b, owner, request)
    assert not b.store.get("artifact", own.id).staged
    assert len(b.store.query("link", {"to_id": own.id})) == 1
    assert not decide(b, owner, request)[1]


def test_stale_gate_and_unrelated_source_rejected_and_historical_comment_allowed(rig):
    b, owner, architect, _, body = rig
    with pytest.raises(BoardError, match="changed"):
        decide(b, owner, body.model_copy(update={"gate_event_id": "ev-other"}))
    other = b.ticket_create(owner, kind=TicketKind.epic, work_type=WorkType.feature, title="Other source")
    with pytest.raises(BoardError, match="not linked"):
        comment(b, owner, DocumentComment(ticket_id=other.id, design_ref=body.design_ref, reviewed_version=1, text="No", idempotency_key="bad"))
    b.doc_update(architect, body.design_ref, body_md="New version")
    comment(b, owner, DocumentComment(ticket_id=body.ticket_id, design_ref=body.design_ref, reviewed_version=1, text="Historical", idempotency_key="history"))
    assert b.open_gates(body.ticket_id)
    assert contextual_work(b, body.ticket_id, "documents")["events"]
    assert all(e["kind"] == "doc_updated" for e in contextual_work(b, body.ticket_id, "documents")["events"])
    assert contextual_work(b, body.ticket_id)["records"][0]["group"] == "Design"
    assert contextual_work(b, other.id)["records"] == []


@pytest.mark.parametrize("transactional", [False, True])
def test_callbacks_release_store_before_taking_board_lock(rig, transactional):
    import threading
    b, *_ = rig
    holding_board = threading.Event()
    callback_entered = threading.Event()
    def publication():
        assert holding_board.wait(2)
        def callback():
            callback_entered.set()
            with b._lock:
                pass
        if transactional:
            with b.store.transaction():
                b.store.after_commit(callback)
        else:
            b.store.after_commit(callback)
    def review():
        with b._lock:
            holding_board.set()
            assert callback_entered.wait(2)
            b.store.max_seq()
    threads = [threading.Thread(target=publication, daemon=True), threading.Thread(target=review, daemon=True)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(3)
    assert all(not thread.is_alive() for thread in threads)


def test_unowned_epic_does_not_grant_typed_review_to_any_owner(rig):
    b, owner, _, _, body = rig
    coordinator = b.participant_create("agent", Role.coordinator, "coordinator")
    ticket = b.ticket(body.ticket_id)
    ticket.created_by = coordinator.id
    b.store.put("ticket", ticket)
    assert b.epic_owner(ticket.id) is None
    with pytest.raises(BoardError, match="matching human owner"):
        decide(b, owner, body)


def test_request_changes_targets_the_source_epics_architect(rig):
    b, owner, _, _, body = rig
    architect = b.participant_create("agent", Role.architect, f"architect.{body.ticket_id}", id_=f"architect.{body.ticket_id}")
    result, _ = decide(b, owner, body.model_copy(update={"decision": "request_changes", "feedback": "Clarify this"}))
    message = b.store.get("message", result["message_id"])
    assert message.to == architect.id
    assert message.ticket_id == body.ticket_id
    assert "resolved to seat" in result["delivery_note"]
    assert b.open_gates(body.ticket_id)


def test_legacy_gate_answer_remains_acceptance_only(rig):
    b, owner, _, _, body = rig
    b.gate_answer(owner, body.ticket_id, Gate.design_signoff, "Approved legacy caller")
    assert b.ticket(body.ticket_id).status == TicketStatus.signed_off


def test_http_requires_actor_and_returns_typed_conflict(rig):
    b, owner, architect, _, body = rig
    client = TestClient(create_app(b))
    assert client.post("/v1/gates/decide", json=body.model_dump()).status_code == 401
    b.doc_update(architect, body.design_ref, body_md="v2")
    response = client.post("/v1/gates/decide", json=body.model_dump(), headers={"X-Participant": owner.id})
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "conflict"
