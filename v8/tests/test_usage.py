"""Cold, synthetic source fixtures; historical installed-source comparison explicitly labelled."""
import io
import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from edp8.board import Board
from edp8.service import create_app
from edp8.store import Store
from edp8.usage import UsageCache, normalize
from edp8.usage_sources import Rpc, SourceError, capture_claude, collect_codex, fingerprint, project, publish

NOW = 1789730000


def receipt(provider="codex", **extra):
    return {"provider": provider, "binding_id": "approved-binding", "status": "available",
            "received_at": "2026-09-18T11:13:20Z", **extra}


def codex(used=0, duration=10080):
    return {"usedPercent": used, "windowDurationMins": duration, "resetsAt": NOW + 10000}


def test_duration_drives_absent_present_absent_and_zero():
    weekly = codex()
    short = codex(23, 300)
    for payload, expected in [({"primary": weekly}, None),
                              ({"primary": weekly, "secondary": short}, 23),
                              ({"secondary": weekly}, None)]:
        result = normalize("codex", receipt(rateLimits=payload), NOW)
        assert result.windows[0].used_percent == expected
        assert result.windows[1].used_percent == 0
        assert result.windows[1].status == "stale"
        assert result.windows[1].observed_at is None
    assert normalize("codex", receipt(rateLimits={"primary": short, "secondary": short}), NOW).windows[0].used_percent is None


def test_documented_codex_pool_authoritative_even_when_empty():
    raw = receipt(rateLimits={"primary": codex()}, rateLimitsByLimitId={"codex": {}})
    assert normalize("codex", raw, NOW).windows[1].used_percent is None
    raw["rateLimitsByLimitId"]["codex"] = {"secondary": codex(44, 300)}
    assert normalize("codex", raw, NOW).windows[0].used_percent == 44


@pytest.mark.parametrize("used", [None, True, "0", -1, 101, float("nan"), float("inf"), 10**400],
                         ids=["null", "bool", "string", "negative", "over100", "nan", "inf", "huge_int"])
def test_invalid_never_zero(used):
    assert normalize("codex", receipt(rateLimits={"primary": codex(used)}), NOW).windows[1].used_percent is None


def test_historical_installed_source_values_not_current_proof():
    # SOURCE-EVIDENCE.md, actual S0 receipt, evaluated at its historical receipt time ONLY.
    raw = receipt("claude", received_at="2026-09-18T08:56:52.591135+00:00", rate_limits={
        "five_hour": {"used_percentage": 0, "resets_at": 1789738200},
        "seven_day": {"used_percentage": 15, "resets_at": 1790251200}})
    result = normalize("claude", raw, 1789721813)
    assert [w.used_percent for w in result.windows] == [0, 15, None]
    assert all(w.observed_at is None for w in result.windows)
    assert result.windows[0].status == "stale"
    assert normalize("claude", raw, 1790251201).windows[1].used_percent is None
    historical = receipt(rateLimits={"primary": {"usedPercent": 92, "windowDurationMins": 10080, "resetsAt": 1789807430}})
    assert normalize("codex", historical, NOW).windows[1].used_percent == 92


def test_receipt_is_not_observation_or_fable():
    raw = receipt("claude", observed_at="2026-09-18T11:13:20Z", rate_limits={
        "five_hour": {"used_percentage": 0, "resets_at": NOW + 9999},
        "fable": {"used_percentage": 35, "resets_at": NOW + 9999}})
    value = normalize("claude", raw, NOW)
    assert value.windows[0].observed_at is None
    assert value.windows[2].used_percent is None
    raw["received_at"] = "2026-09-17T11:13:20Z"
    assert "older than five" in normalize("claude", raw, NOW).windows[0].reason
    raw["received_at"] = "2099-09-17T11:13:20Z"
    assert normalize("claude", raw, NOW).windows[0].status == "error"


@pytest.mark.parametrize("status", ["auth_required", "error", "unavailable"])
def test_explicit_terminal_states_hide_numbers(status):
    value = normalize("codex", receipt(status=status, rateLimits={"primary": codex(55)}), NOW)
    assert value.windows[1].status == status
    assert value.windows[1].used_percent is None


def setup_cache(tmp_path):
    snapshot = tmp_path / "codex.json"
    config = tmp_path / "usage.json"
    config.write_text(json.dumps({"participants": {"alice": {"codex": {
        "binding_id": "approved-binding", "snapshot": str(snapshot)}}}}))
    clock = [NOW]
    return UsageCache(config, clock=lambda: clock[0]), clock, snapshot, config


def test_cache_backoff_acl_revocation_and_binding_change(tmp_path):
    cache, clock, snapshot, config = setup_cache(tmp_path)
    value = cache.read("alice")["providers"][1]
    assert value["windows"][0]["status"] == "unavailable"
    snapshot.write_text(json.dumps(receipt(rateLimits={"primary": codex()})))
    assert cache.read("alice")["providers"][1]["windows"][1]["used_percent"] is None
    clock[0] += 31
    assert cache.read("alice")["providers"][1]["windows"][1]["used_percent"] == 0
    assert cache.read("bob")["providers"][1]["windows"][1]["used_percent"] is None
    config.write_text('{"participants":{}}')
    assert cache.read("alice")["providers"][1]["account_binding"] is None
    config.write_text(json.dumps({"participants": {"alice": {"codex": {
        "binding_id": "different", "snapshot": str(snapshot)}}}}))
    assert cache.read("alice")["providers"][1]["windows"][1]["status"] == "auth_required"
    clock[0] += 31
    assert cache.read("alice")["providers"][1]["retry_after_seconds"] == 60


def test_cache_automatic_updates_and_expiry(tmp_path):
    cache, clock, snapshot, _ = setup_cache(tmp_path)
    for payload, expected in [({"primary": codex()}, None),
                              ({"primary": codex(), "secondary": codex(7, 300)}, 7),
                              ({"primary": codex()}, None)]:
        snapshot.write_text(json.dumps(receipt(rateLimits=payload)))
        clock[0] += 31
        assert cache.read("alice")["providers"][1]["windows"][0]["used_percent"] == expected
    clock[0] += 10001
    assert cache.read("alice")["providers"][1]["windows"][1]["used_percent"] is None


@pytest.mark.parametrize("content", ["[]", "not json", "x" * 65537], ids=["array", "malformed", "oversize"])
def test_safe_parse_failures(tmp_path, content):
    cache, _, snapshot, _ = setup_cache(tmp_path)
    snapshot.write_text(content)
    result = cache.read("alice")
    assert result["providers"][1]["windows"][0]["status"] == "error"
    assert "not json" not in json.dumps(result)


def test_endpoint_auth_no_actor_selector_or_credential_leak(tmp_path, monkeypatch):
    cache, _, snapshot, config = setup_cache(tmp_path)
    snapshot.write_text(json.dumps(receipt(rateLimits={"primary": codex()}, token="SECRET", email="private@example.test")))
    monkeypatch.setenv("EDP8_USAGE_CONFIG", str(config))
    monkeypatch.setenv("EDP8_HOME", str(tmp_path))
    monkeypatch.setenv("EDP8_PUBLIC", "0")
    monkeypatch.setenv("EDP8_TOKENS", str(tmp_path / "tokens.json"))
    (tmp_path / "tokens.json").write_text(json.dumps({"alice": "a", "bob": "b"}))
    app = create_app(Board(Store(":memory:")), admin_token="t")
    with TestClient(app) as client:
        for who in ("alice", "bob"):
            assert client.post("/v1/participants", json={"id": who, "handle": who, "role": "owner", "type": "human"}, headers={"X-Admin": "t"}).status_code == 200
        assert client.get("/v1/me/usage").status_code == 401
        assert client.get("/v1/me/usage", headers={"X-Participant": "alice"}).status_code == 401
        result = client.get("/v1/me/usage", headers={"X-Participant": "alice", "X-Token": "a"})
        assert result.status_code == 200
        assert result.headers["cache-control"] == "private, no-store"
        for private in ("SECRET", "private@example", "approved-binding", str(snapshot)):
            assert private not in result.text
        result = client.get("/v1/me/usage?participant_id=alice", headers={"X-Participant": "bob", "X-Token": "b"})
        assert result.json()["value"]["providers"][1]["account_binding"] is None


def test_capture_allowlist_atomic_and_bound(tmp_path):
    path = tmp_path / "claude.json"
    capture_claude(io.BytesIO(json.dumps({"secret": "NEVER", "rate_limits": {"five_hour": {
        "used_percentage": 0, "resets_at": NOW + 10000}}}).encode()), path, "binding-test")
    value = json.loads(path.read_text())
    assert value["rate_limits"]["five_hour"]["used_percentage"] == 0
    assert value["observed_at"] is None
    assert "NEVER" not in path.read_text()
    for data in (b"[]", b"x" * 65537):
        with pytest.raises(ValueError):
            capture_claude(io.BytesIO(data), path, "binding-test")
    assert json.loads(path.read_text()) == value
    assert not list(tmp_path.glob(".usage-*"))


def test_codex_fingerprint_and_wrong_account_refused(tmp_path):
    account = {"account": {"type": "chatgpt", "id": "synthetic", "email": "private"}}
    expected = fingerprint(account)
    assert len(expected) == 64 and "synthetic" not in expected
    assert fingerprint({"account": {"type": "apiKey"}}) is None
    class Fake:
        changed = False
        def call(self, method):
            assert method == "account/read"  # never request another account's rate limits
            return account
    path = tmp_path / "codex.json"
    collect_codex(Fake(), path, "approved-binding", "0" * 64, once=True)
    assert json.loads(path.read_text())["status"] == "auth_required"


def test_codex_supported_read_projection(tmp_path):
    account = {"account": {"type": "chatgpt", "email": "synthetic@example.test"}}
    class Fake:
        changed = False
        def latest_rate_update(self, payload):
            return payload
        def call(self, method):
            return account if method == "account/read" else {"rateLimits": {"primary": codex(0)}, "token": "NEVER"}
    path = tmp_path / "codex.json"
    collect_codex(Fake(), path, "approved-binding", fingerprint(account), once=True)
    value = json.loads(path.read_text())
    assert value["rateLimits"]["primary"]["usedPercent"] == 0
    assert "NEVER" not in path.read_text()


def test_codex_events_replace_windows_and_account_change_hides_data(tmp_path, monkeypatch):
    account = {"account": {"type": "chatgpt", "email": "synthetic@example.test"}}
    payloads = [
        {"rateLimits": {"primary": codex(), "secondary": codex(5, 300)}},
        {"rateLimits": {"primary": codex()}},
    ]
    class Fake:
        changed = False
        def latest_rate_update(self, payload):
            return payload
        def call(self, method):
            return account if method == "account/read" else {"rateLimits": {"primary": codex()}}
        def next(self, timeout):
            if payloads:
                return {"method": "account/rateLimits/updated", "params": payloads.pop(0)}
            raise StopIteration
    writes = []
    monkeypatch.setattr("edp8.usage_sources.publish", lambda path, value: writes.append(value))
    with pytest.raises(StopIteration):
        collect_codex(Fake(), tmp_path / "codex.json", "approved-binding", fingerprint(account))
    assert [r["rateLimits"].get("secondary", {}).get("usedPercent") for r in writes] == [None, 5, None]
    # A changed account during the quota read prevents publication of its numbers.
    class Changed(Fake):
        def call(self, method):
            result = super().call(method)
            if method == "account/rateLimits/read":
                self.changed = True
            return result
    writes.clear()
    collect_codex(Changed(), tmp_path / "codex.json", "approved-binding", fingerprint(account), once=True)
    assert writes[0]["status"] == "auth_required"


def test_rpc_cleanup_on_broken_stdin_and_owned_child_timeout(monkeypatch):
    import subprocess
    class Broken(io.StringIO):
        def close(self):
            super().close()
            raise BrokenPipeError
    class Process:
        def __init__(self):
            self.stdin = Broken()
            self.stdout = io.StringIO('{"id":1,"result":{}}\n')
            self.waits = 0
            self.terminated = self.killed = False
        def wait(self, timeout):
            self.waits += 1
            if self.waits < 3:
                raise subprocess.TimeoutExpired("owned", timeout)
        def terminate(self):
            self.terminated = True
        def kill(self):
            self.killed = True
    process = Process()
    monkeypatch.setattr("edp8.usage_sources.subprocess.Popen", lambda *a, **kw: process)
    rpc = Rpc("synthetic-executable")
    rpc.reader.join(timeout=1)
    assert rpc.call("initialize") == {}
    with pytest.raises(SourceError):
        rpc.call("account/read")
    rpc.close()
    assert process.terminated and process.killed and process.stdout.closed and process.stdin.closed


def test_source_errors_and_default_off_do_not_disclose(tmp_path, monkeypatch):
    monkeypatch.delenv("EDP8_USAGE_CONFIG", raising=False)
    assert all(p["account_binding"] is None for p in UsageCache().read("alice")["providers"])
    account = {"account": {"type": "chatgpt", "email": "synthetic@example.test"}}
    class Failed:
        changed = False
        def call(self, method):
            raise SourceError("secret provider error must not escape")
    path = tmp_path / "codex.json"
    collect_codex(Failed(), path, "approved-binding", fingerprint(account), once=True)
    assert json.loads(path.read_text())["status"] == "error"
    assert "secret" not in path.read_text()


def test_huge_integers_project_and_cache_without_overflow(tmp_path):
    raw = {"rateLimits": {"primary": codex(10**400)}}
    projected = project("codex", raw, "approved-binding")
    assert projected["rateLimits"]["primary"]["usedPercent"] is None
    cache, _, snapshot, _ = setup_cache(tmp_path)
    snapshot.write_text(json.dumps(receipt(**raw)))
    assert cache.read("alice")["providers"][1]["windows"][1]["used_percent"] is None
    path = tmp_path / "claude.json"
    capture_claude(io.BytesIO(json.dumps({"rate_limits": {"five_hour": {
        "used_percentage": 10**400, "resets_at": 10**400}}}).encode()), path, "binding-test")
    assert json.loads(path.read_text())["rate_limits"]["five_hour"]["used_percentage"] is None


def test_real_rpc_interleaving_preserves_post_read_removal_in_once_mode(tmp_path):
    import queue
    import threading
    from types import SimpleNamespace
    account = {"account": {"type": "chatgpt", "email": "synthetic@example.test"}}
    short = {"rateLimits": {"primary": codex(), "secondary": codex(7, 300)}}
    absent = {"rateLimits": {"primary": codex()}}
    rpc = Rpc.__new__(Rpc)
    rpc.process = SimpleNamespace(stdin=io.StringIO())
    rpc.serial = 0
    rpc.changed = False
    rpc.pending_rates = []
    rpc.failed = threading.Event()
    rpc.messages = queue.Queue()
    for message in [
        {"method": "account/rateLimits/updated", "params": absent},
        {"id": 1, "result": account},
        {"method": "account/rateLimits/updated", "params": absent},
        {"id": 2, "result": short},
        {"method": "account/rateLimits/updated", "params": short},
        {"method": "account/rateLimits/updated", "params": absent},
        {"id": 3, "result": account},
    ]:
        rpc.messages.put(message)
    path = tmp_path / "codex.json"
    collect_codex(rpc, path, "approved-binding", fingerprint(account), once=True)
    assert "secondary" not in json.loads(path.read_text())["rateLimits"]
    assert rpc.messages.empty() and rpc.pending_rates == []

