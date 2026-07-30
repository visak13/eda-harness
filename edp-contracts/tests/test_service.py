"""TESTPLAN §1 (service) + §6 (contract tests)."""

import builtins

import pytest

from edp_contracts import HealthStatus, Microservice


class _Svc(Microservice):
    name = "edp-mock"
    version = "1.0.0"

    async def startup(self) -> None:
        self.started = True

    async def shutdown(self) -> None:
        self.stopped = True

    async def health(self) -> HealthStatus:
        return HealthStatus(status="ready", version=self.version)


async def test_svc_1_conforming():
    """SVC-1 MUST."""
    s = _Svc()
    h = await s.health()
    assert isinstance(h, HealthStatus)
    assert h.status == "ready" and h.version == "1.0.0"


def test_svc_2_abc_enforced():
    """SVC-2 MUST — missing shutdown() cannot instantiate."""

    class _Bad(Microservice):
        name = "x"
        version = "1"

        async def startup(self) -> None: ...

        async def health(self) -> HealthStatus: ...  # no shutdown

    with pytest.raises(TypeError):
        _Bad()


def test_svc_3_healthstatus_validates():
    """SVC-3 MUST."""
    with pytest.raises(Exception):
        HealthStatus(status="up", version="1")  # 'up' not in Literal


def test_svc_4_mount_without_fastapi_clear_error(monkeypatch):
    """SVC-4 MUST — module imports fine; mount() w/o FastAPI raises clearly."""
    import edp_contracts.service as svc  # import always works

    real_import = builtins.__import__

    def _no_fastapi(name, *a, **k):
        if name == "fastapi":
            raise ModuleNotFoundError("No module named 'fastapi'")
        return real_import(name, *a, **k)

    monkeypatch.setattr(builtins, "__import__", _no_fastapi)
    with pytest.raises(ImportError, match=r"edp-contracts\[service\]"):
        svc.mount(object(), _Svc())  # type: ignore[arg-type]


def test_svc_5_mount_wires_health():
    """SVC-5 SHOULD + CON-1 MUST — /v1/health spec-correct."""
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from edp_contracts import mount
    from edp_contracts.service import HEALTH_PATH

    app = FastAPI()
    mount(app, _Svc())
    with TestClient(app) as client:
        r = client.get(HEALTH_PATH)
        assert r.status_code == 200
        body = r.json()
        # extra=forbid honored: exactly the HealthStatus fields
        assert set(body) == {"status", "version", "detail", "deps"}
        assert body["status"] == "ready"


def test_con_2_exception_becomes_envelope():
    """CON-2 MUST — unhandled route error => ToolError-shaped JSON."""
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from edp_contracts import mount

    app = FastAPI()
    mount(app, _Svc())

    @app.get("/boom")
    async def _boom():
        raise RuntimeError("kaboom")

    with TestClient(app, raise_server_exceptions=False) as client:
        r = client.get("/boom")
        assert r.status_code == 500
        body = r.json()
        assert body["ok"] is False
        assert body["source"] == "edp-mock"
        assert body["code"] == "unhandled_exception"
        assert "kaboom" in body["message"]


def test_con_3_envelope_violation_loud():
    """CON-3 MUST — non-envelope upstream raises (not silent ToolError)."""
    from edp_contracts import Tool
    from edp_contracts.errors import EnvelopeViolation

    class _R:
        def json(self):
            return {"oops": 1}

    with pytest.raises(EnvelopeViolation):
        Tool.from_upstream(_R())
