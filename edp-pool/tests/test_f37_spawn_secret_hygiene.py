"""F37#8 (2026-08-18) — secret hygiene at the spawn boundary.

The pool env used to be copied WHOLE into every spawned shell, so any
provider credential the operator had exported reached every worker.
Credential-shaped names are stripped; the stack's own families (EDP_*,
ANTHROPIC_*, CLAUDE_*) and the EDP_SPAWN_ENV_KEEP allowlist pass through.
"""
import os

from edp_pool.pty_launcher import _strip_foreign_secrets, build_env


def test_strip_drops_credential_shaped_names():
    env = _strip_foreign_secrets({
        "OPENAI_API_KEY": "sk-x", "MY_SECRET": "s", "GH_TOKEN": "t",
        "DB_PASSWORD": "p", "AWS_CREDENTIALS": "c", "SSH_PRIVATE_KEY": "k",
        "PATH": "keep", "SystemRoot": "keep",
    })
    assert "PATH" in env and "SystemRoot" in env
    for gone in ("OPENAI_API_KEY", "MY_SECRET", "GH_TOKEN", "DB_PASSWORD",
                 "AWS_CREDENTIALS", "SSH_PRIVATE_KEY"):
        assert gone not in env


def test_strip_keeps_stack_families_and_explicit_keep(monkeypatch):
    monkeypatch.setenv("EDP_SPAWN_ENV_KEEP", "OPENAI_API_KEY")
    env = _strip_foreign_secrets({
        "EDP_BRIDGE_TOKEN_THING": "stack", "ANTHROPIC_API_KEY": "harness",
        "CLAUDE_CODE_OAUTH_TOKEN": "harness", "OPENAI_API_KEY": "kept",
        "COHERE_API_KEY": "dropped",
    })
    assert env["EDP_BRIDGE_TOKEN_THING"] == "stack"
    assert env["ANTHROPIC_API_KEY"] == "harness"
    assert env["CLAUDE_CODE_OAUTH_TOKEN"] == "harness"
    assert env["OPENAI_API_KEY"] == "kept"
    assert "COHERE_API_KEY" not in env


def test_build_env_applies_the_strip(monkeypatch):
    monkeypatch.setenv("SOME_VENDOR_API_KEY", "leakme")
    monkeypatch.delenv("EDP_SPAWN_ENV_KEEP", raising=False)
    env = build_env(role="worker", handle="p1:a1", session_id="s",
                    broker_url=None, pool_url=None, agent_home=None,
                    log_dir=None, defaults={})
    assert "SOME_VENDOR_API_KEY" not in env
    assert env["EDP_ROLE"] == "worker"          # stack stamps intact


# ── F40#13 — EDP_PARENT lineage stamp for bare-handle seats ────────────────
def test_build_env_stamps_parent_when_given(monkeypatch):
    monkeypatch.delenv("EDP_PARENT", raising=False)
    env = build_env(role="acceptor", handle="acceptor-ab12", session_id="s",
                    broker_url=None, pool_url=None, agent_home=None,
                    log_dir=None, defaults={}, parent="r9")
    assert env["EDP_PARENT"] == "r9"


def test_build_env_never_inherits_a_foreign_parent(monkeypatch):
    monkeypatch.setenv("EDP_PARENT", "someone-elses-recipe")
    env = build_env(role="worker", handle="p1:a1", session_id="s",
                    broker_url=None, pool_url=None, agent_home=None,
                    log_dir=None, defaults={}, parent=None)
    assert "EDP_PARENT" not in env
