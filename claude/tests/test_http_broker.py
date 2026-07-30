"""HttpBroker (consumer BrokerPort) — fake httpx, no network.

C2 (DESIGN-v6 s18): the fast per-tick poll must ride a dedicated 2-5s timeout,
NOT the shared 30s httpx client, so a hung broker cannot stall a reconcile tick.
"""

from edp_claude.clients.http_broker import POLL_TIMEOUT_S, HttpBroker


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
        self.last_get_kwargs = None  # capture per-call kwargs (e.g. timeout)

    async def get(self, url, params=None, **kwargs):
        self.last_get_kwargs = {"params": params, **kwargs}
        return self._get


async def test_poll_uses_bounded_fast_timeout_not_shared_30s():
    c = _Client(get=_Resp(200, []))
    out = await HttpBroker("http://b", c).poll("recipient:a1")
    assert out == []                       # empty inbox parses cleanly
    assert c.last_get_kwargs.get("timeout") == POLL_TIMEOUT_S
    assert 2.0 <= POLL_TIMEOUT_S <= 5.0
    assert POLL_TIMEOUT_S != 30.0
