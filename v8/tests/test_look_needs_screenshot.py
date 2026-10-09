"""t-cf891f387b (owner m-b1fe71dcca: "Does the QA role never use playwright to look at the UI?"): a check=look
criterion passes on what was seen. The board refuses verdict=pass until an image is uploaded on the criterion's
ticket; a fail, and every other check kind, need none."""
from __future__ import annotations

import pytest

from edp8.board import BoardError
from edp8.schemas import ArtifactForm, Check, TicketKind, Verdict, WorkType
from test_stuck_criteria import b, r, to_in_review  # noqa: F401  (fixtures)


def _story(b, r):
    return b.ticket_create(r["architect"], kind=TicketKind.story, work_type=WorkType.feature, title="S",
                           parent_id=r["epic"].id)


def _shot(b, actor, ticket_id, content_type="image/png"):
    a = b.artifact_upload(actor, form=ArtifactForm.image, content_type=content_type, filename="walk.png")
    b.artifact_finalise(actor, artifact_ids=[a.id], ticket_id=ticket_id)
    return a


def test_a_look_pass_without_a_screenshot_is_advised_and_with_one_is_quiet(b, r):
    from edp8 import advice
    s = _story(b, r)
    c = to_in_review(b, r, s, r["engineer"], check=Check.look)
    advice.take()
    assert b.criterion_update(r["qa"], c.id, verdict=Verdict.passed).verdict == Verdict.passed
    [said] = [x for x in advice.take() if "screenshot" in x]  # design-63db8a7d42 I: advice, the pass stands
    assert s.id in said and "passed as given" in said
    s2 = _story(b, r)
    c2 = to_in_review(b, r, s2, r["engineer"], check=Check.look)
    _shot(b, r["engineer"], s2.id)
    advice.take()
    assert b.criterion_update(r["qa"], c2.id, verdict=Verdict.passed).verdict == Verdict.passed
    assert not [x for x in advice.take() if "screenshot" in x]


def test_a_staged_upload_or_a_non_image_does_not_count(b, r):
    from edp8 import advice
    s = _story(b, r)
    c = to_in_review(b, r, s, r["engineer"], check=Check.look)
    b.artifact_upload(r["engineer"], form=ArtifactForm.image, content_type="image/png")  # staged: never posted
    _shot(b, r["engineer"], s.id, content_type="text/plain")
    advice.take()
    b.criterion_update(r["qa"], c.id, verdict=Verdict.passed)
    assert [x for x in advice.take() if "screenshot" in x]


def test_a_shot_from_before_the_latest_in_review_does_not_count(b, r):
    """qa m-5954b2e825: an earlier build's shot (here, one posted while the story was still in progress) is not
    what the pass rests on; the advice says no image was uploaded since it went in_review."""
    from edp8 import advice
    s = _story(b, r)
    _shot(b, r["engineer"], s.id)  # before the hand-off
    c = to_in_review(b, r, s, r["engineer"], check=Check.look)
    advice.take()
    b.criterion_update(r["qa"], c.id, verdict=Verdict.passed)
    assert any("since it went in_review" in x for x in advice.take())


def test_a_look_fail_and_other_checks_need_no_screenshot(b, r):
    s = _story(b, r)
    c = to_in_review(b, r, s, r["engineer"], check=Check.look)
    assert b.criterion_update(r["qa"], c.id, verdict=Verdict.failed).verdict == Verdict.failed
    s2 = _story(b, r)
    c2 = to_in_review(b, r, s2, r["engineer"], check=Check.command)
    assert b.criterion_update(r["qa"], c2.id, verdict=Verdict.passed).verdict == Verdict.passed


def test_the_owners_own_look_verdict_needs_no_screenshot(b, r):
    s = _story(b, r)
    c = to_in_review(b, r, s, r["engineer"], check=Check.look, checked_by="owner")
    assert b.criterion_update(r["owner"], c.id, verdict=Verdict.passed).verdict == Verdict.passed
