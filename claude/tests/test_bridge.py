"""Unit tests for the provider bridge engine (tools/bridge.py) — pure parts
only, mirroring test_sol_bridge.py's discipline: no network, no codex binary."""

import json

import pytest

from edp_claude.tools import bridge
from edp_claude.tools.bridge import (
    BridgeError,
    Delegate,
    approx_tokens,
    build_http_payload,
    build_work_order,
    check_budget,
    estimate_cost,
    parse_config,
    parse_findings,
    route_for,
)

# ── config parsing ───────────────────────────────────────────────────────────

def _cfg(**over):
    base = {
        "delegates": {
            "sol": {"backend": "cli", "model": "gpt-5.6", "effort": "medium"},
            "flash": {"backend": "http", "model": "flash-x",
                      "base_url": "https://api.example.com/v1",
                      "api_key_env": "FLASH_KEY",
                      "price_in_per_mtok": 0.1, "price_out_per_mtok": 0.4},
        },
        "routes": {"worker:codegen": "flash", "curiosity:*": "sol"},
    }
    base.update(over)
    return base


def test_parse_config_roundtrip():
    delegates, routes = parse_config(_cfg())
    assert delegates["sol"].backend == "cli"
    assert delegates["sol"].effort == "medium"
    assert delegates["flash"].api_key_env == "FLASH_KEY"
    assert routes["worker:codegen"] == "flash"


def test_parse_config_timeout_secs_per_delegate():
    # F34-h (campaign R3): a deep delegate's longer wall clock is a CONFIG
    # decision — parsed per delegate, default None (sol_bridge's 900s).
    cfg = _cfg()
    cfg["delegates"]["sol"]["timeout_secs"] = 1800
    delegates, _ = parse_config(cfg)
    assert delegates["sol"].timeout_secs == 1800.0
    assert delegates["flash"].timeout_secs is None


def test_parse_config_rejects_bad_backend():
    with pytest.raises(BridgeError, match="backend"):
        parse_config({"delegates": {"x": {"backend": "grpc", "model": "m"}}})


def test_parse_config_rejects_http_without_key_env():
    with pytest.raises(BridgeError, match="api_key_env"):
        parse_config({"delegates": {"x": {
            "backend": "http", "model": "m", "base_url": "https://x"}}})


def test_parse_config_rejects_route_to_unknown_delegate():
    cfg = _cfg()
    cfg["routes"]["worker:*"] = "nope"
    with pytest.raises(BridgeError, match="unknown delegate"):
        parse_config(cfg)


def test_live_repo_config_is_valid():
    """The checked-in claude/.bridge.json must always parse."""
    raw = json.loads(bridge.config_path().read_text(encoding="utf-8")) \
        if bridge.config_path().is_file() else None
    if raw is None:
        pytest.skip("no .bridge.json at agent home in this test env")
    delegates, routes = parse_config(raw)
    assert "sol" in delegates and delegates["sol"].backend == "cli"


# ── routing ──────────────────────────────────────────────────────────────────

def test_route_exact_beats_wildcard_and_absent_means_none():
    _, routes = parse_config(_cfg())
    assert route_for("worker", "codegen", routes) == "flash"
    assert route_for("curiosity", "anything", routes) == "sol"
    assert route_for("reviewer", "codegen", routes) is None


# ── work orders ──────────────────────────────────────────────────────────────

def test_work_order_contains_all_sections_and_contract():
    o = build_work_order(task="do X", context="ctx", acceptance="passes tests",
                         kind="challenge")
    assert "do X" in o and "ctx" in o and "passes tests" in o
    assert "JSON array of findings" in o          # adversary output contract


def test_work_order_rejects_empty_task_and_bad_kind():
    with pytest.raises(BridgeError, match="empty"):
        build_work_order(task="  ")
    with pytest.raises(BridgeError, match="kind"):
        build_work_order(task="x", kind="destroy")


def test_budget_refuses_oversized_order_loudly():
    d = Delegate(name="tiny", backend="http", model="m",
                 base_url="https://x", api_key_env="K",
                 max_context_tokens=100, max_output_tokens=50)
    with pytest.raises(BridgeError, match="never\\s+truncates"):
        check_budget(d, "x" * 4000)


# ── http payload + cost ──────────────────────────────────────────────────────

def test_http_payload_shape_and_effort_optional():
    d = Delegate(name="f", backend="http", model="flash-x",
                 base_url="https://x", api_key_env="K", effort="medium")
    p = build_http_payload(d, "hello")
    assert p["model"] == "flash-x"
    assert p["messages"][0]["content"] == "hello"
    assert p["reasoning_effort"] == "medium"
    d2 = Delegate(name="f", backend="http", model="flash-x",
                  base_url="https://x", api_key_env="K")
    assert "reasoning_effort" not in build_http_payload(d2, "hi")


def test_cost_estimate_and_subscription_is_free():
    d = Delegate(name="f", backend="http", model="m", base_url="https://x",
                 api_key_env="K", price_in_per_mtok=1.0, price_out_per_mtok=4.0)
    assert estimate_cost(d, 1_000_000, 500_000) == pytest.approx(3.0)
    cli = Delegate(name="sol", backend="cli", model="gpt-5.6")
    assert estimate_cost(cli, 10**6, 10**6) == 0.0


def test_approx_tokens_floor():
    assert approx_tokens("") == 1
    assert approx_tokens("x" * 400) == 100


# ── challenge findings parsing (defensive) ───────────────────────────────────

def test_parse_findings_happy_path_and_severity_default():
    content = ('preamble the model should not have written '
               '[{"finding": "acceptance omits auth", "evidence": "no test", '
               '"severity": "high", "target": "a3"}, '
               '{"finding": "loose claim"}] trailing')
    got = parse_findings(content)
    assert got[0]["severity"] == "high" and got[0]["target"] == "a3"
    assert got[1]["severity"] == "medium"          # bad/missing → medium


def test_parse_findings_garbage_yields_empty_never_raises():
    assert parse_findings("I refuse to answer in JSON") == []
    assert parse_findings("[not json") == []
    assert parse_findings("") == []
