"""C8 (s-a4fd5df319): the pure classifier of scripts/tailnet_readiness.py over fixed facts (no tailscale,
no pool, no board, no fleet files)."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

SPEC = importlib.util.spec_from_file_location(
    "tailnet_readiness", Path(__file__).resolve().parents[1] / "scripts" / "tailnet_readiness.py")
tr = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(tr)

NAME = "msi.tail884b19.ts.net"
SECRET = "s3cr3t-admin-value"


def facts(**over):
    f = {
        "planned": False,
        "env": {"EDP8_ADMIN_TOKEN": {"value": SECRET, "source": ".env", "persistent": {}},
                "EDP8_PUBLIC_URL": {"value": None, "source": "unset", "persistent": {}},
                "EDP8_HOST": {"value": "127.0.0.1", "source": ".env", "persistent": {}}},
        "tokens_path": "tokens.json",
        "tokens": {"humans": ["owner"], "agents": ["architect.e", "engineer.s"]},
        "humans": ["owner"],
        "seats": ["architect.e", "engineer.s"],
        "tailscale": {"backend": "Running", "dns": NAME, "cert_domains": [NAME], "peers": 0},
        "serve": {},
        "ports": {"board": 9400, "mcp": 9402, "pool": 9301, "broker": 9300, "code-server": 9410},
        "listeners": {9400: ["127.0.0.1"], 9402: ["127.0.0.1"], 9301: ["127.0.0.1"], 9300: ["127.0.0.1"],
                      9410: ["127.0.0.1"]},
    }
    f.update(over)
    return f


def blockers(f):
    return [(r["area"], r["text"]) for r in tr.classify(f) if r["level"] == "BLOCKER"]


def test_a_ready_host_has_no_blockers_and_never_prints_the_secret():
    rows = tr.classify(facts())
    assert not [r for r in rows if r["level"] == "BLOCKER"]
    assert SECRET not in json.dumps(rows) and SECRET not in tr.render(rows)


def test_default_admin_token_blocks_unless_planned():
    env = facts()["env"] | {"EDP8_ADMIN_TOKEN": {"value": None, "source": "unset", "persistent": {}}}
    assert any(a == "admin token" for a, _ in blockers(facts(env=env)))
    assert not any(a == "admin token" for a, _ in blockers(facts(env=env, planned=True)))


def test_unpinned_or_wide_bind_blocks():
    for host in (None, "0.0.0.0", "100.72.192.76"):
        env = facts()["env"] | {"EDP8_HOST": {"value": host, "source": ".env", "persistent": {}}}
        assert any(a == "bind" for a, _ in blockers(facts(env=env))), host


def test_untokened_live_seat_blocks_and_names_the_remedy():
    rows = tr.classify(facts(seats=["architect.e", "engineer.new"]))
    b = [r for r in rows if r["level"] == "BLOCKER"]
    assert len(b) == 1 and "engineer.new" in b[0]["text"] and "respawn" in b[0]["fix"]


def test_human_without_token_is_a_warning_not_a_blocker():
    rows = tr.classify(facts(humans=["owner", "x"]))
    assert not [r for r in rows if r["level"] == "BLOCKER"]
    assert any(r["level"] == "WARN" and "'x'" in r["text"] for r in rows)


def test_certificates_off_or_tailscale_down_block():
    assert any(a == "certificates" for a, _ in blockers(facts(tailscale={"backend": "Running", "dns": NAME,
                                                                         "cert_domains": [], "peers": 0})))
    assert any(a == "tailscale" for a, _ in blockers(facts(tailscale=None)))


def test_serve_config_only_the_https_board_front_passes():
    good = {"TCP": {"443": {"HTTPS": True}}, "Web": {f"{NAME}:443": {"Handlers": {"/": {"Proxy": "http://127.0.0.1:9400"}}}}}
    assert not blockers(facts(serve=good))
    code = {"Web": {f"{NAME}:443": {"Handlers": {"/": {"Proxy": "http://127.0.0.1:9410"}}}}}
    assert any("code-server" in t for _, t in blockers(facts(serve=code)))
    funnel = dict(good, AllowFunnel={f"{NAME}:443": True})
    assert any("Funnel" in t for _, t in blockers(facts(serve=funnel)))
    raw = {"TCP": {"9400": {"TCPForward": "127.0.0.1:9400"}}}
    assert any("TCP forward" in t for _, t in blockers(facts(serve=raw)))


def test_non_loopback_listener_blocks_per_service():
    ls = facts()["listeners"] | {9300: ["0.0.0.0"], 9410: ["::"]}
    areas = [t for a, t in blockers(facts(listeners=ls)) if a == "listen"]
    assert any("broker" in t for t in areas) and any("code-server" in t for t in areas)


def test_public_url_must_be_the_tailnet_name_and_persistent_env_blocks():
    env = facts()["env"] | {"EDP8_PUBLIC_URL": {"value": "https://other.example", "source": ".env", "persistent": {}}}
    assert any(a == "public url" for a, _ in blockers(facts(env=env)))
    env = facts()["env"] | {"EDP8_ADMIN_TOKEN": {"value": SECRET, "source": "persistent env",
                                                 "persistent": {"user": SECRET}}}
    rows = tr.classify(facts(env=env))
    assert any(r["area"] == "real env" and r["level"] == "BLOCKER" for r in rows)
    assert SECRET not in json.dumps(rows)


def test_read_dotenv_matches_start_ps1(tmp_path):
    f = tmp_path / ".env"
    f.write_text("# c\nA=1\nB = two  # note\nA=3\nbad line\n", encoding="utf-8")
    assert tr.read_dotenv(f) == {"A": "3", "B": "two"}
