"""measure_codex_containment — the LIVE MCP surface of a codex thread under each containment arg set.

    python scripts/measure_codex_containment.py [-o out.json]

Starts `codex app-server` (no turn, no inference) with the -c set of: consult's design and concept profiles
before the hidden-feature fix (mcp_disable_args), after it (mcp_containment_args, t-1b6d0f546f), and the codex
seat's own containment (edp8.codex_seat.seat.containment_args, board server not added); opens an ephemeral
thread and records `mcpServerStatus/list`. "live" = a tool catalog or runtimeStatus other than "disabled".
Exit 0 when every after-fix / seat set is empty (the seat adds only edp8 on top). s-10a2b1f9ec.
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from edp8.codex_seat.rpc import AppServer  # noqa: E402
from edp8.codex_seat.seat import containment_args  # noqa: E402
from edp8.consult import _PROFILES, _profile_config_args, discover_mcp_servers, mcp_containment_args, mcp_disable_args  # noqa: E402


def live_set(codex: str, args: list[str], sandbox: str) -> dict[str, dict]:
    d = Path(tempfile.mkdtemp(prefix="contain-"))
    srv = AppServer([codex, "app-server", *args], cwd=os.getcwd(), env=dict(os.environ), log_path=d / "m.jsonl",
                    on_notification=lambda m, p: None, on_request=lambda m, p: None)
    srv.start()
    try:
        srv.request("initialize", {"clientInfo": {"name": "measure", "title": "measure", "version": "1"},
                                   "capabilities": {"experimentalApi": True, "requestAttestation": False}})
        srv.notify("initialized")
        tid = srv.request("thread/start", {"cwd": os.getcwd(), "sandbox": sandbox, "approvalPolicy": "never",
                                           "ephemeral": True}, timeout=120)["thread"]["id"]
        res = srv.request("mcpServerStatus/list", {"threadId": tid}, timeout=120)
    finally:
        srv.stop()
    return {s["name"]: {"runtimeStatus": s.get("runtimeStatus"), "tools": len(s.get("tools") or {})}
            for s in res.get("data", [])}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("-o", "--out")
    a = ap.parse_args(argv)
    codex = os.environ.get("EDP_CODEX_BIN") or shutil.which("codex")
    servers, err = discover_mcp_servers(codex)
    if err:
        print(err, file=sys.stderr)
        return 2
    out: dict = {"discovered": sorted(s["name"] for s in servers), "runs": {}}
    for label, contain in (("before_fix", mcp_disable_args), ("after_fix", mcp_containment_args)):
        for prof in ("design", "concept"):
            spec = _PROFILES[prof]
            out["runs"][f"consult/{prof}/{label}"] = live_set(codex, _profile_config_args(spec) + contain(servers), spec.sandbox)
    out["runs"]["codex_seat/no_board"] = live_set(codex, containment_args(codex)[0] + ["-c", "approval_policy=never"], "read-only")
    for k, v in out["runs"].items():
        out.setdefault("live", {})[k] = sorted(n for n, s in v.items() if s["tools"] or s["runtimeStatus"] not in (None, "disabled"))
    s = json.dumps(out, indent=1)
    if a.out:
        Path(a.out).write_text(s, encoding="utf-8")
    print(json.dumps(out["live"], indent=1))
    ok = all(not v for k, v in out["live"].items() if not k.endswith("before_fix"))
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
