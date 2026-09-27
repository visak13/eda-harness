"""Owner m-da9a2ae62f (t-cd4712c855): "no way anyone can launch the owner role". The pool is the last line:
whatever the caller (the board, the MCP spawn tool, the panel, a script), a person's role or a handle naming
one is refused before any shell starts, and never resumed."""

import pytest
from fastapi.testclient import TestClient

from edp_contracts.roles import NON_AGENT_ROLES
from edp_pool.service import PoolService, create_app
from edp_pool.spawner import FakeSpawner


@pytest.fixture
def svc():
    return PoolService(FakeSpawner())


@pytest.mark.parametrize("role", sorted(NON_AGENT_ROLES))
def test_spawn_refuses_a_person_role(svc, role):
    res = svc.spawn(role, f"{role}.e-1", None)
    assert not isinstance(res, str) and res.code == "pool_role_refused"
    assert "person" in res.message and svc.sessions == {} and svc.locks == {}


def test_spawn_refuses_a_person_handle_under_an_agent_role(svc):
    for handle in ("owner", "owner.e-1", "@expert.t-2"):
        res = svc.spawn("worker", handle, None)
        assert not isinstance(res, str) and res.code == "pool_role_refused", handle
    assert svc.sessions == {}
    assert isinstance(svc.spawn("worker", "engineer.e-1", None), str)  # an agent seat still starts


def test_resume_never_brings_back_a_person(svc):
    for handle in ("owner", "expert.e-1"):
        out = svc.resume(handle)
        assert out["resumed"] is False and "person" in out["reason"]
        assert svc.resume_closed(handle)["resumed"] is False


def test_http_spawn_refuses_the_owner():
    c = TestClient(create_app(FakeSpawner()))
    r = c.post("/v1/spawn", json={"role": "owner", "handle": "owner"})
    body = r.json()
    assert "pool_role_refused" in r.text and not body.get("ok", False), r.text
    assert c.get("/v1/locks").json() == []


def test_seat_model_for_refuses_a_person_role(tmp_path):
    """qa c-c0b35be596: the pool's model lookup gives a person's role no model (owner m-da9a2ae62f)."""
    from edp_contracts.roles import NonAgentRole
    from edp_pool.spawner import seat_model_for
    (tmp_path / "models.json").write_text('{"role_models": {"engineer": ["m1"]}, "roles": {"owner": "x"},'
                                          ' "seats": {"x": {"model": "m0"}}}', encoding="utf-8")
    for role in ("owner", "expert", "human"):
        with pytest.raises(NonAgentRole):
            seat_model_for(role, str(tmp_path))
    assert seat_model_for("engineer", str(tmp_path)) == "m1"
