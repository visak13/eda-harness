"""W14 (DESIGN-v6) — pool doctor: five stack-health checks + endpoint.

Every network ping is MOCKED — the checks probe through the `doctor._http_get`
seam, and the CLI lock-fetch has its OWN httpx seam in `doctor._fetch_locks`.
BOTH are mocked here, so no test depends on whether a port is live or dead:
Phoenix may be up or down on :6006 and these tests read the same. The
claude-binary check runs against a FABRICATED npm layout under tmp_path — the
real claude.exe is never read or written. Asserts the Phoenix-down path
DEGRADES to a warning (not an error), that each of the five checks runs, and
that the /v1/doctor endpoint returns the same checks as JSON.

d7 note: the doctor code path reads neither EDP_ROLE nor EDP_HANDLE (it does
not call build_env or role-scoped registration), so no env pin/clear is
required here — unlike the W4/build_env tests. If that ever changes, pin
them per d7.
"""
import httpx

from edp_pool import doctor
from edp_pool import pty_launcher as pl

_HEALTHY = pl._MIN_HEALTHY_BIN_BYTES + 10
_STUB = 500


def _make_install(root, *, bin_bytes, source_bytes=None):
    """Fabricate an npm claude-code layout under `root` (mirrors the W14
    launcher tests). Returns the resolved bin path (str)."""
    adir = root / "node_modules" / "@anthropic-ai"
    binp = adir / "claude-code" / "bin" / "claude.exe"
    binp.parent.mkdir(parents=True, exist_ok=True)
    binp.write_bytes(b"\0" * bin_bytes)
    if source_bytes is not None:
        src = (adir / "claude-code" / "node_modules" / "@anthropic-ai"
               / "claude-code-win32-x64" / "claude.exe")
        src.parent.mkdir(parents=True, exist_ok=True)
        src.write_bytes(b"\0" * source_bytes)
    return str(binp)


def _fake_http(mapping):
    """Build an _http_get replacement: `mapping` maps a url-substring to a
    (reachable, status_code, error) tuple; the first matching substring
    wins, default = unreachable."""
    def _get(url, timeout):
        for frag, result in mapping.items():
            if frag in url:
                return result
        return (False, None, "no route")
    return _get


_UP = (True, 200, None)
_DOWN = (False, None, "Connection refused")


# ── binary check (real reuse of pty_launcher.repair) ───────────────────────
def test_claude_binary_healthy_is_ok(tmp_path):
    binp = _make_install(tmp_path, bin_bytes=_HEALTHY)
    r = doctor.check_claude_binary(binp)
    assert r["status"] == "ok"
    assert "healthy" in r["detail"]


def test_claude_binary_stub_is_repaired(tmp_path):
    """A sub-1MB stub with a versions-cache source is REPAIRED via the
    shared repair_claude_install — reported "ok" (not error)."""
    binp = _make_install(tmp_path, bin_bytes=_STUB, source_bytes=_HEALTHY)
    r = doctor.check_claude_binary(binp)
    assert r["status"] == "ok"
    assert "repaired" in r["detail"]
    assert pl.claude_bin_needs_repair(binp) is False


def test_claude_binary_unrepairable_is_error(tmp_path):
    """A stub with NO source cannot be repaired — the check is "error" and
    carries the refuse-and-explain fix (the neuron relays, never runs)."""
    binp = _make_install(tmp_path, bin_bytes=_STUB, source_bytes=None)
    r = doctor.check_claude_binary(binp)
    assert r["status"] == "error"
    assert "python -m edp_pool.doctor" in r["detail"]


# ── Phoenix degrade-to-warning (the headline W14 requirement) ──────────────
def test_phoenix_down_is_warning_not_error(monkeypatch):
    # The MOCK makes Phoenix unreachable — not the environment. This asserts
    # the degrade rule itself, identically whether or not :6006 is live.
    monkeypatch.setattr(doctor, "_http_get", _fake_http({"6006": _DOWN}))
    r = doctor.check_phoenix("http://localhost:6006", 1.0)
    assert r["status"] == "warn"
    assert "degraded" in r["detail"]


def test_phoenix_up_is_ok(monkeypatch):
    monkeypatch.setattr(doctor, "_http_get", _fake_http({"6006": _UP}))
    r = doctor.check_phoenix("http://localhost:6006", 1.0)
    assert r["status"] == "ok"


# ── required-service pings ─────────────────────────────────────────────────
def test_http_health_up_is_ok(monkeypatch):
    monkeypatch.setattr(doctor, "_http_get", _fake_http({"9300": _UP}))
    r = doctor.check_http_health("broker", "http://127.0.0.1:9300", 1.0)
    assert r["status"] == "ok"


def test_http_health_down_is_error(monkeypatch):
    monkeypatch.setattr(doctor, "_http_get", _fake_http({"9300": _DOWN}))
    r = doctor.check_http_health("broker", "http://127.0.0.1:9300", 1.0)
    assert r["status"] == "error"
    assert "unreachable" in r["detail"]


def test_http_health_non_200_is_error(monkeypatch):
    monkeypatch.setattr(
        doctor, "_http_get", _fake_http({"9301": (True, 503, None)}))
    r = doctor.check_http_health("pool", "http://127.0.0.1:9301", 1.0)
    assert r["status"] == "error"
    assert "503" in r["detail"]


# ── stale-lock sweep (diagnostic, never reaps) ─────────────────────────────
def test_stale_locks_none_is_ok():
    locks = [{"handle": "h1", "session_id": "s1", "liveness": "alive"}]
    r = doctor.check_stale_locks(locks)
    assert r["status"] == "ok"


def test_stale_locks_dead_holder_is_warning():
    locks = [
        {"handle": "h1", "session_id": "s1", "liveness": "alive"},
        {"handle": "h2", "session_id": "s2", "liveness": "dead"},
    ]
    r = doctor.check_stale_locks(locks)
    assert r["status"] == "warn"
    assert "h2" in r["detail"]
    assert "h1" not in r["detail"]  # a live lock is not flagged


def test_stale_locks_empty_is_ok():
    r = doctor.check_stale_locks([])
    assert r["status"] == "ok"


# ── full run: every check runs + healthy-stack budget ──────────────────────
def test_run_doctor_all_checks_run_and_healthy(tmp_path, monkeypatch):
    """All five checks run in order, a healthy stack is ok=True, and the run
    fits the <10s acceptance budget (mocked pings make it near-instant)."""
    monkeypatch.setattr(
        doctor, "_http_get",
        _fake_http({"9300": _UP, "9301": _UP, "6006": _UP}))
    binp = _make_install(tmp_path, bin_bytes=_HEALTHY)

    report = doctor.run_doctor(claude_bin=binp, locks=[])

    names = [c["name"] for c in report["checks"]]
    assert names == ["claude_binary", "broker", "pool", "phoenix",
                     "seat_registry", "config_parity", "foreground_model",
                     "stale_locks"]
    # v7 WS4: the registry/parity checks WARN in a hermetic env (no
    # EDP_AGENT_HOME) by design — absent config is staged-legacy, never an
    # error. Everything else must be strictly ok, and nothing may error.
    for c in report["checks"]:
        if c["name"] in ("seat_registry", "config_parity",
                         "foreground_model"):
            assert c["status"] in ("ok", "warn"), c
        else:
            assert c["status"] == "ok", c
    assert report["ok"] is True
    assert report["elapsed_ms"] < 10_000
    assert all("elapsed_ms" in c for c in report["checks"])


def test_run_doctor_phoenix_down_stays_healthy(tmp_path, monkeypatch):
    """Phoenix down (warn) does NOT fail the doctor — ok stays True; broker
    down (error) DOES."""
    monkeypatch.setattr(
        doctor, "_http_get",
        _fake_http({"9300": _UP, "9301": _UP, "6006": _DOWN}))
    binp = _make_install(tmp_path, bin_bytes=_HEALTHY)

    report = doctor.run_doctor(claude_bin=binp, locks=[])

    phoenix = next(c for c in report["checks"] if c["name"] == "phoenix")
    assert phoenix["status"] == "warn"
    assert report["ok"] is True


def test_run_doctor_broker_down_is_unhealthy(tmp_path, monkeypatch):
    monkeypatch.setattr(
        doctor, "_http_get",
        _fake_http({"9300": _DOWN, "9301": _UP, "6006": _UP}))
    binp = _make_install(tmp_path, bin_bytes=_HEALTHY)

    report = doctor.run_doctor(claude_bin=binp, locks=[])

    assert report["ok"] is False


def test_run_doctor_fetches_locks_when_not_injected(tmp_path, monkeypatch):
    """CLI path: with no `locks=` injected the sweep reads the pool's
    /v1/locks over HTTP; an unreachable pool degrades the sweep to a warn
    (not a crash). `_fetch_locks` uses httpx directly (not the _http_get
    seam), so it is mocked at its OWN seam — pointing the fetch at a dead
    port would make the environment, not the code, decide the outcome."""
    monkeypatch.setattr(
        doctor, "_http_get",
        _fake_http({"9300": _UP, "9301": _UP, "6006": _UP}))
    fetched_from = []

    def _unreachable_pool(pool_url, timeout):
        fetched_from.append(pool_url)
        return [], "Connection refused"

    monkeypatch.setattr(doctor, "_fetch_locks", _unreachable_pool)
    binp = _make_install(tmp_path, bin_bytes=_HEALTHY)

    report = doctor.run_doctor(
        claude_bin=binp, pool_url="http://127.0.0.1:9301")

    # the CLI path really did fetch, against the pool it was given
    assert fetched_from == ["http://127.0.0.1:9301"]
    sweep = next(c for c in report["checks"] if c["name"] == "stale_locks")
    assert sweep["status"] == "warn"
    assert "sweep skipped" in sweep["detail"]


def test_fetch_locks_unreachable_pool_returns_reason_not_raises(monkeypatch):
    """The real `_fetch_locks` behind the mock above: a transport failure
    returns ([], reason) instead of raising — that contract is what lets the
    sweep degrade rather than crash the whole doctor run."""
    def _refused(url, timeout):
        raise httpx.ConnectError("Connection refused")

    monkeypatch.setattr(doctor.httpx, "get", _refused)

    locks, err = doctor._fetch_locks("http://127.0.0.1:9301", 1.0)

    assert locks == []
    assert "Connection refused" in err


# ── the service endpoint returns the same checks as JSON ───────────────────
def test_doctor_endpoint_returns_checks_json(monkeypatch):
    from fastapi.testclient import TestClient

    from edp_pool.service import create_app
    from edp_pool.spawner import FakeSpawner

    monkeypatch.setattr(
        doctor, "_http_get",
        _fake_http({"9300": _UP, "9301": _UP, "6006": _DOWN}))
    # Hermetic: the endpoint resolves the REAL claude bin (no override path
    # through HTTP), so stub the binary check — it never touches/repairs the
    # actual install. Its own logic is covered by the direct tests above.
    monkeypatch.setattr(
        doctor, "check_claude_binary",
        lambda claude_bin=None: {
            "name": "claude_binary", "status": "ok",
            "detail": "stubbed", "elapsed_ms": 0})
    client = TestClient(create_app(FakeSpawner()))

    resp = client.get("/v1/doctor")

    assert resp.status_code == 200
    body = resp.json()
    names = [c["name"] for c in body["checks"]]
    assert names == ["claude_binary", "broker", "pool", "phoenix",
                     "seat_registry", "config_parity", "foreground_model",
                     "stale_locks"]
    # Phoenix down is a warn, so the endpoint still reports a well-formed
    # payload with the ok flag present.
    assert "ok" in body
    phoenix = next(c for c in body["checks"] if c["name"] == "phoenix")
    assert phoenix["status"] == "warn"


# -- WP4 (2026-08-12): foreground-model parity check ------------------------
def _write_registry(home, neuron_model):
    import json
    (home / "models.json").write_text(json.dumps({
        "seats": {"judgment": {"model": neuron_model}},
        "roles": {"neuron": "judgment"},
    }), encoding="utf-8")


def _write_pin(cfg_dir, model):
    import json
    cfg_dir.mkdir(parents=True, exist_ok=True)
    (cfg_dir / "settings.json").write_text(
        json.dumps({"model": model}), encoding="utf-8")


def test_foreground_model_skew_warns(tmp_path, monkeypatch):
    home = tmp_path / "agent"; home.mkdir()
    _write_registry(home, "claude-opus-4-6")
    cfg = tmp_path / "cfgdir"
    _write_pin(cfg, "claude-fable-5[1m]")
    monkeypatch.setenv("EDP_AGENT_HOME", str(home))
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(cfg))
    r = doctor.check_foreground_model()
    assert r["status"] == "warn" and "SKEW" in r["detail"]


def test_foreground_model_match_is_ok_mode_suffix_ignored(tmp_path, monkeypatch):
    home = tmp_path / "agent"; home.mkdir()
    _write_registry(home, "claude-opus-4-6")
    cfg = tmp_path / "cfgdir"
    _write_pin(cfg, "claude-opus-4-6[1m]")
    monkeypatch.setenv("EDP_AGENT_HOME", str(home))
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(cfg))
    r = doctor.check_foreground_model()
    assert r["status"] == "ok"


def test_foreground_model_missing_settings_warns_not_errors(tmp_path, monkeypatch):
    home = tmp_path / "agent"; home.mkdir()
    _write_registry(home, "claude-opus-4-6")
    monkeypatch.setenv("EDP_AGENT_HOME", str(home))
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(tmp_path / "nope"))
    r = doctor.check_foreground_model()
    assert r["status"] == "warn" and "not checked" in r["detail"]
