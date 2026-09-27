"""S11 F2 (t-e355a990f7, adversary m-1438a061ec): a role's human flag is data and never makes an agent a human.

Lint refuses a human+spawnable role and an agent role among a gate's answerers, and a custom role gets the
escalation checks whatever its flag; at runtime an agent never answers a gate and an agent in a custom
human-flagged role never passes a role check, even on a published definition that skipped the lint.
"""
import pytest

from edp8 import workflow as wf
from edp8.board import Board, BoardError
from edp8.schemas import Gate, Role, TicketKind, WorkType
from edp8.store import Store


def _robot_def(b: Board, new_id: str) -> dict:
    """The adversary's repro: Standard + robot {human, spawnable, gate_answerer} answering `adversarial`."""
    d = wf.dump(b.workflows.duplicate('standard@1', new_id=new_id, by='owner'))
    d['roles'].append({'id': 'robot', 'human': True, 'spawnable': True, 'capacity_class': 'checker',
                       'card_md': '# robot\nReview.', 'bundle': ['gate_answer'], 'gate_answerer': True})
    next(r for r in d['roles'] if r['id'] == 'architect')['may_spawn'].append('robot')
    next(g for g in d['gates'] if g['id'] == 'adversarial')['answerers'].append('robot')
    return d


def _codes(d: dict) -> set[str]:
    return {p['code'] for p in wf.validate(d) if p['severity'] == 'error'}


def test_lint_refuses_human_spawnable_role_and_publish_fails():
    b = Board(Store(':memory:'))
    d = _robot_def(b, 'f2lint')
    assert 'human_spawnable' in _codes(d)
    b.workflows.save(d, by='owner')
    with pytest.raises(wf.WorkflowError) as e:
        b.workflows.publish(d['id'], d['version'], by='owner')
    assert 'human_spawnable' in {p['code'] for p in e.value.problems}


def test_lint_refuses_agent_role_among_gate_answerers():
    b = Board(Store(':memory:'))
    d = wf.dump(b.workflows.duplicate('standard@1', new_id='f2answer', by='owner'))
    next(g for g in d['gates'] if g['id'] == 'adversarial')['answerers'].append('qa')
    assert 'agent_answerer' in _codes(d)  # the owner still answers it, but an agent role must not


def test_custom_human_role_gets_the_escalation_checks():
    b = Board(Store(':memory:'))
    d = wf.dump(b.workflows.duplicate('standard@1', new_id='f2esc', by='owner'))
    d['roles'].append({'id': 'lead', 'human': True, 'bundle': ['spawn'], 'criterion_checker': True,
                       'capacity_class': 'builder'})
    codes = _codes(d)
    assert {'escalation', 'self_check'} <= codes
    # a non-spawnable human role answering gates is what a human role is for
    d['roles'][-1] = {'id': 'lead', 'human': True, 'gate_answerer': True, 'bundle': ['gate_answer']}
    next(g for g in d['gates'] if g['id'] == 'adversarial')['answerers'].append('lead')
    assert not _codes(d) & {'escalation', 'self_check', 'human_spawnable', 'agent_answerer'}


def test_standard_still_lints_clean():
    b = Board(Store(':memory:'))
    for ref in ('standard@1',):
        assert not _codes(wf.dump(b.workflows.resolve(ref).d))


def _published_without_lint(b: Board) -> str:
    """A hand-crafted published definition that never went through validate/publish (e.g. an old DB row)."""
    d = _robot_def(b, 'f2runtime')
    saved = b.workflows.save(d, by='owner')
    b.workflows._put(saved.model_copy(update={'published': True}), 'owner')
    return saved.ref


def test_agent_cannot_answer_a_gate_on_a_definition_that_skipped_lint():
    b = Board(Store(':memory:'))
    ref = _published_without_lint(b)
    owner = b.participant_create('human', Role.owner, 'owner', id_='owner')
    arch = b.participant_create('agent', Role.architect, 'arch', id_='arch')
    epic = b.ticket_create(owner, kind=TicketKind.epic, work_type=WorkType.feature,
                           title='F2 probe', workflow=ref)
    robot = b.participant_create('agent', 'robot', 'robot', id_='robot')
    b.gate_open(epic.id, Gate.adversarial, by=arch.id)
    with pytest.raises(BoardError) as e:
        b.gate_answer(robot, epic.id, Gate.adversarial, 'approved by agent')
    assert e.value.code == 'scope'
    assert b.open_gates(epic.id, Gate.adversarial)
    # the rule is the participant's type: a person holding the same role answers it
    person = b.participant_create('human', 'robot', 'rhuman', id_='rhuman')
    assert b.gate_answer_refusal(person, epic.id, Gate.adversarial) is None


def test_agent_in_custom_human_role_never_passes_a_role_check():
    b = Board(Store(':memory:'))
    ref = _published_without_lint(b)
    owner = b.participant_create('human', Role.owner, 'owner', id_='owner')
    epic = b.ticket_create(owner, kind=TicketKind.epic, work_type=WorkType.feature,
                           title='F2 role probe', workflow=ref)
    w = b.workflow_of(epic.id)
    robot = b.participant_create('agent', 'robot', 'robot', id_='robot')
    person = b.participant_create('human', 'robot', 'rhuman', id_='rhuman')
    assert wf.agent_in_human_role(w, robot) and not wf.agent_in_human_role(w, person)
    params = {'roles': ['robot']}
    assert wf._p_role_in(wf.Ctx(b, robot, epic, w), params) is not None
    assert wf._p_role_in(wf.Ctx(b, person, epic, w), params) is None
