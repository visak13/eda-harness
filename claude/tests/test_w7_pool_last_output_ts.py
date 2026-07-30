"""W7 item 2 — pool busyness signal `last_output_ts`.

`liveness(handle)` now returns `{state, last_output_ts}` end to end:
- the pool's `/v1/liveness/{handle}` endpoint carries `last_output_ts`
  (the epoch mtime of the shell's PTY-drain log — the busyness signal),
- `HttpPool.liveness` (the consumer PoolPort) parses it through verbatim,
- `StubPool.liveness` mirrors the shape so the in-process tests + every
  swept call site see the same dict.

The pool-SIDE mtime derivation (spawner.last_output_ts +
PoolService.last_output_ts + the endpoint dict) is unit-tested in the
edp-pool package's OWN suite (edp_pool is not importable from claude's
.venv). Here we prove the CLIENT contract + that a real mtime flows
through the endpoint shape unchanged.
"""

from edp_claude.clients import HttpPool
from edp_claude.stubs.stub_pool import StubPool


class _Resp:
    def __init__(self, status, payload):
        self.status_code = status
        self._p = payload

    def json(self):
        return self._p

    def raise_for_status(self):
        if self.status_code // 100 != 2:
            raise AssertionError("unexpected")


class _Client:
    def __init__(self, get=None):
        self._get = get

    async def get(self, url, **kwargs):     # accept per-call kwargs (C2 timeout)
        return self._get


# ── HttpPool (consumer): endpoint {state,last_output_ts} → dict ──────────

async def test_httppool_liveness_returns_state_and_output_ts():
    c = _Client(get=_Resp(
        200, {"handle": "p:a1", "state": "alive", "last_output_ts": 1720000000.5}))
    out = await HttpPool("http://p", c).liveness("p:a1")
    assert out == {"state": "alive", "last_output_ts": 1720000000.5}


async def test_httppool_liveness_output_ts_absent_is_none():
    # A pool that predates the busyness field (state only) must not KeyError;
    # last_output_ts degrades to None (pass-through, forward-compatible).
    c = _Client(get=_Resp(200, {"handle": "p:a1", "state": "unknown"}))
    out = await HttpPool("http://p", c).liveness("p:a1")
    assert out == {"state": "unknown", "last_output_ts": None}


async def test_httppool_real_mtime_flows_through_the_endpoint(tmp_path):
    # Prove a REAL log-file mtime (what the pool derives last_output_ts from)
    # round-trips through the endpoint shape into HttpPool unchanged.
    log = tmp_path / "worker_p_a1.log"
    log.write_bytes(b"\xef\xbb\xbfsome drained PTY output\n")
    mtime = log.stat().st_mtime
    c = _Client(get=_Resp(
        200, {"handle": "p:a1", "state": "alive", "last_output_ts": mtime}))
    out = await HttpPool("http://p", c).liveness("p:a1")
    assert out["state"] == "alive"
    assert out["last_output_ts"] == mtime


# ── StubPool: mirrors the {state,last_output_ts} shape ──────────────────

async def test_stubpool_liveness_is_dict_with_state_and_output_ts():
    pool = StubPool()
    await pool.spawn_worker("p1", "a1")
    live = await pool.liveness("p1:a1")
    assert live == {"state": "alive", "last_output_ts": None}


async def test_stubpool_set_output_ts_surfaces_as_last_output_ts():
    pool = StubPool()
    await pool.spawn_worker("p1", "a1")
    pool.set_output_ts("p1:a1", 1720000123.0)
    live = await pool.liveness("p1:a1")
    assert live["state"] == "alive"
    assert live["last_output_ts"] == 1720000123.0


async def test_stubpool_dead_keeps_state_and_output_ts_shape():
    pool = StubPool()
    await pool.spawn_worker("p1", "a1")
    pool.set_output_ts("p1:a1", 42.0)
    pool.mark_dead("p1:a1")
    live = await pool.liveness("p1:a1")
    # a crashed shell still returns the dict; state flips to dead, the last
    # observed output ts is preserved (it says WHEN it last spoke).
    assert live == {"state": "dead", "last_output_ts": 42.0}


async def test_stubpool_unknown_handle_is_dict_with_none_output_ts():
    pool = StubPool()
    live = await pool.liveness("never:spawned")
    assert live == {"state": "unknown", "last_output_ts": None}
