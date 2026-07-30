"""The Microservice contract — uniform lifecycle + health + wiring.

Every microservice (edp-broker, edp-pool, edp-fsm, future edp-memory-svc)
implements :class:`Microservice` and is mounted via :func:`mount`, so the
operator/pool can manage them all identically.

FastAPI is imported lazily inside :func:`mount` so importers that only need
the Tool ABC / envelopes (e.g. the claude/ repo) never pay for FastAPI and
keep their <2s startup budget (HLD §2.2).
"""

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING, Literal

from pydantic import BaseModel, ConfigDict, Field

if TYPE_CHECKING:  # import only for type-checkers, never at runtime
    from fastapi import FastAPI

# HealthState/DepState stay `Literal` (not StrEnum): they are only ever used
# as Pydantic field types where Literal is idiomatic and gives the same
# validation. S3b refactor decision — enum would add an import for no gain.
HealthState = Literal["ready", "degraded", "starting", "stopping"]
DepState = Literal["ok", "down", "unknown"]

#: The one uniform health route every microservice exposes.
HEALTH_PATH = "/v1/health"

# Structured-log `kind` values emitted by mount() wiring.
_KIND_REQUEST_IN = "request_in"
_KIND_REQUEST_OUT = "request_out"
_KIND_UNHANDLED = "unhandled_exception"


class HealthStatus(BaseModel):
    """Uniform health payload returned by ``GET /v1/health``."""

    model_config = ConfigDict(extra="forbid")

    status: HealthState
    version: str  # semver of the /v1 HTTP surface (NOT the package version)
    detail: str = ""
    deps: dict[str, DepState] = Field(default_factory=dict)


class Microservice(ABC):
    """Abstract base every microservice implements.

    ``name`` and ``version`` are class attributes set by the subclass.
    ``version`` is the semver of the ``/v1`` HTTP surface; a breaking
    surface change ships ``/v2`` and bumps it.
    """

    name: str
    version: str

    @abstractmethod
    async def startup(self) -> None: ...

    @abstractmethod
    async def shutdown(self) -> None: ...

    @abstractmethod
    async def health(self) -> HealthStatus: ...


def mount(app: "FastAPI", service: Microservice) -> None:
    """Wire the uniform surface onto a FastAPI app.

    Adds, identically for every microservice:
      * ``GET /v1/health`` -> ``service.health()``
      * startup/shutdown hooks -> ``service.startup()`` / ``service.shutdown()``
      * a structured-logging middleware (one LogRecordModel line per request)
      * an exception handler turning any unhandled error into ToolError-shaped
        JSON (never a raw stack trace to a caller)

    FastAPI is imported here (lazily) so the package's hard dependency stays
    pydantic + stdlib only. If FastAPI is absent, this raises a clear
    ImportError naming the ``edp-contracts[service]`` extra.
    """
    try:
        from fastapi import Request
        from fastapi.responses import JSONResponse
    except ModuleNotFoundError as exc:  # pragma: no cover - env-specific
        raise ImportError(
            "edp_contracts.service.mount() needs FastAPI. Install the extra: "
            "pip install 'edp-contracts[service]'"
        ) from exc

    from .errors import ErrorCode
    from .logging import get_logger
    from .tool import ToolError

    log = get_logger(service.name)

    # Starlette's add_event_handler() was removed in recent FastAPI; the
    # router's on_startup/on_shutdown lists are the stable, version-robust
    # surface for appending lifecycle hooks onto an already-built app.
    app.router.on_startup.append(service.startup)
    app.router.on_shutdown.append(service.shutdown)

    @app.get(HEALTH_PATH)
    async def _health() -> dict:  # noqa: D401 - simple wiring
        status = await service.health()
        return status.model_dump(mode="json")

    @app.middleware("http")
    async def _structured_log(request: "Request", call_next):  # noqa: ANN001
        log.info(
            _KIND_REQUEST_IN,
            f"{request.method} {request.url.path}",
            path=request.url.path,
            method=request.method,
        )
        response = await call_next(request)
        log.info(
            _KIND_REQUEST_OUT,
            f"{request.method} {request.url.path} -> {response.status_code}",
            path=request.url.path,
            status=response.status_code,
        )
        return response

    @app.exception_handler(Exception)
    async def _envelope_exc(request: "Request", exc: Exception):  # noqa: ANN001
        log.error(_KIND_UNHANDLED, f"{type(exc).__name__}: {exc}")
        err = ToolError(
            source=service.name,
            code=ErrorCode.UNHANDLED_EXCEPTION,
            message=f"{type(exc).__name__}: {exc}",
            retryable=False,
        )
        return JSONResponse(status_code=500, content=err.model_dump(mode="json"))
