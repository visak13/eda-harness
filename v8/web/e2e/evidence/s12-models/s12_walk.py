"""S12 t-186b964fb1 (c-14b676e73d / c-2482f1c0f3): a PRIVATE heronry instance (free ports, temp EDP_HOME, env
marker) -> init (claude) -> start -> s12_walk.mjs (setup with pi selected, Admin -> Models: add a Pi model,
role default, test spawn, New Epic SeatPicks, remove) -> stop; no survivors. Reuses s6_walk.py's recipe."""
import json
import os
import re
import subprocess
import sys
import uuid
from pathlib import Path

V8 = Path(r"C:\Work\Learning\eda-base3\v8")
sys.path.insert(0, str(V8 / "tests"))
import test_cli_launcher as base  # noqa: E402
from edp_contracts.proc import kill_tree, scan_env_marker  # noqa: E402

HERE = Path(__file__).parent
OUT = Path(sys.argv[1])
tmp = HERE / f"s12inst-{uuid.uuid4().hex[:6]}"
tmp.mkdir()
board, mcp, pool, broker = base._free_ports(4)
env = {k: v for k, v in os.environ.items() if not k.startswith(("EDP", "HERONRY", "CLAUDE_CONFIG_DIR", "PYTHONPATH"))}
env.update(EDP_HOME=str(tmp / "home"), EDP_CLAUDE_CONFIG_DIR=str(tmp / "claude"),
           EDP8_PORT=str(board), EDP8_MCP_PORT=str(mcp), EDP_POOL_PORT=str(pool), EDP_BROKER_PORT=str(broker),
           EDP8_EMBEDDER="none", PYTHONIOENCODING="utf-8", HERONRY_NO_UPDATE_CHECK="1",
           # the Pi provider's credential for this walk (a placeholder: the test spawn is a stub, no tokens spent)
           OPENROUTER_API_KEY="walk-placeholder")
env.pop("GROQ_API_KEY", None)  # the refusal step adds a groq model with no credential
env[base.MARKER] = uuid.uuid4().hex
for svc, project in (("POOL", base.ROOT / "edp-pool"), ("BROKER", base.ROOT / "edp-broker")):
    env[f"EDP_{svc}_PYTHON"] = str(base._venv_py(project))
inst = {"env": env, "ports": {"board": board, "mcp": mcp, "pool": pool, "broker": broker}, "home": tmp / "home"}
print("ports", inst["ports"], flush=True)
rc = 1
try:
    r = base.cli(inst, "init", "--harness", "claude", "--agent-home-source", str(V8))
    print(r.stdout[-1500:], r.stderr[-800:], flush=True)
    assert r.returncode == 0
    mj = inst["home"] / "agent-home" / "models.json"
    if mj.exists():  # the fleet models.json `harnesses` key would override the walk's selection
        reg = json.loads(mj.read_text(encoding="utf-8"))
        print("agent-home models.json harnesses key:", reg.pop("harnesses", None), flush=True)
        mj.write_text(json.dumps(reg, indent=2), encoding="utf-8")
    r = base.cli(inst, "start", "--no-browser")
    print(re.sub(r"code=[^ ]+", "code=<redacted>", r.stdout), r.stderr[-800:], flush=True)
    assert r.returncode == 0
    m = re.search(r"(http://\S+/ui/setup\?code=\S+)", r.stdout)
    assert m, "start printed no setup link"
    wenv = {**os.environ, "SETUP_URL": m.group(1), "BOARD": f"http://127.0.0.1:{board}", "OUT": str(OUT)}
    w = subprocess.run(["node", str(HERE / "s12_walk.mjs")], env=wenv, timeout=600)
    rc = w.returncode
    cat = next(inst["home"].rglob("models.json"), None)
    print("catalog files:", [str(p) for p in inst["home"].rglob("models.json")], flush=True)
finally:
    s = base.cli(inst, "stop")
    print("stop", s.returncode, s.stdout[-600:], flush=True)
    for ident in scan_env_marker(base.MARKER, env[base.MARKER]):
        kill_tree(ident, grace=2.0)
    print("survivors", scan_env_marker(base.MARKER, env[base.MARKER]), flush=True)
sys.exit(rc)
