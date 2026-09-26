"""tailnet_readiness.py — READ-ONLY check: what would block the board's public mode over the tailnet (C8).

    .venv\\Scripts\\python.exe scripts\\tailnet_readiness.py            current config, as if EDP8_PUBLIC_URL were set now
    .venv\\Scripts\\python.exe scripts\\tailnet_readiness.py --planned  as `edp.ps1 tailnet apply` will write it
                                                                     (EDP8_HOST=127.0.0.1, EDP8_PUBLIC_URL, a
                                                                     generated admin token when it is the default)
    add --json for a machine-readable report

Exit 0 = no BLOCKER; 1 = at least one BLOCKER; 2 = the check itself failed. It never writes a file, never
changes tailscale, never restarts anything, and never prints a token value (only handles and yes/no).
Shape (design-10b21760d9 §4.3): board on 127.0.0.1:9400, `tailscale serve --https=443 http://127.0.0.1:9400`,
EDP8_PUBLIC_URL=https://<tailnet name> so public mode's fail-closed token rules apply.
"""

from __future__ import annotations

import argparse
import ipaddress
import json
import os
import re
import sqlite3
import subprocess
import sys
import urllib.request
from pathlib import Path

V8 = Path(__file__).resolve().parent.parent
KEYS = ("EDP8_ADMIN_TOKEN", "EDP8_PUBLIC_URL", "EDP8_HOST")
DEFAULT_ADMIN = "dev"
# every fleet listener that must stay loopback after the switch (steer m-6c5309e95e)
PORTS = {"board": ("EDP8_PORT", 9400), "mcp": ("EDP8_MCP_PORT", 9402), "pool": ("EDP_POOL_PORT", 9301),
         "broker": ("EDP_BROKER_PORT", 9300), "code-server": ("EDP_CODE_PORT", 9410)}


# ------------------------------------------------------------------------------------------ facts
def read_dotenv(path: Path) -> dict[str, str]:
    """v8/.env exactly as start.ps1/edp.ps1 read it: # comments, `k=v`, inline ` #` comment dropped, last wins."""
    out: dict[str, str] = {}
    try:
        lines = path.read_text(encoding="utf-8-sig").splitlines()
    except OSError:
        return out
    for line in lines:
        t = line.strip()
        if not t or t.startswith("#") or "=" not in t:
            continue
        k, v = t.split("=", 1)
        out[k.strip()] = re.split(r"\s+#", v, maxsplit=1)[0].strip()
    return out


def _persistent_env(name: str) -> dict[str, str]:
    """User/Machine-scope values (a real environment beats .env in start.ps1). Windows only."""
    found: dict[str, str] = {}
    try:
        import winreg
    except ImportError:
        return found
    for scope, root, sub in (("user", winreg.HKEY_CURRENT_USER, "Environment"),
                             ("machine", winreg.HKEY_LOCAL_MACHINE,
                              r"SYSTEM\CurrentControlSet\Control\Session Manager\Environment")):
        try:
            with winreg.OpenKey(root, sub) as k:
                found[scope] = str(winreg.QueryValueEx(k, name)[0])
        except OSError:
            pass
    return found


def _run(cmd: list[str]) -> tuple[int, str]:
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=20)
        return p.returncode, p.stdout
    except (OSError, subprocess.TimeoutExpired) as e:
        return 127, str(e)


def _get_json(url: str):
    try:
        with urllib.request.urlopen(url, timeout=10) as r:
            return json.loads(r.read().decode("utf-8"))
    except Exception:  # noqa: BLE001 — unreachable is a fact, reported by the classifier
        return None


def listeners() -> dict[int, list[str]]:
    """port -> local addresses in LISTENING state (netstat, IPv4 + IPv6)."""
    out: dict[int, list[str]] = {}
    _, text = _run(["netstat", "-ano", "-p", "TCP"])
    _, text6 = _run(["netstat", "-ano", "-p", "TCPv6"])
    for line in (text + "\n" + text6).splitlines():
        parts = line.split()
        if len(parts) >= 4 and parts[0].startswith("TCP") and parts[3] == "LISTENING":
            addr, _, port = parts[1].rpartition(":")
            if port.isdigit():
                out.setdefault(int(port), []).append(addr.strip("[]"))
    return out


def gather(planned: bool) -> dict:
    env_file = read_dotenv(V8 / ".env")
    eff: dict[str, dict] = {}
    for k in KEYS:
        # what a fresh owner shell running edp.ps1 sees: a User/Machine value beats v8/.env. The caller's
        # own process env is ignored on purpose — a seat shell inherits the board's EDP8_HOST et al.
        pers = _persistent_env(k)
        val = pers.get("user") or pers.get("machine") or env_file.get(k)
        eff[k] = {"value": val, "source": "persistent env" if pers else (".env" if k in env_file else "unset"),
                  "persistent": pers}
    tokens_path = Path(os.environ.get("EDP8_TOKENS") or (Path(os.environ.get("EDP8_HOME") or V8) / "tokens.json"))
    tokens: dict | None
    try:
        raw = json.loads(tokens_path.read_text(encoding="utf-8"))
        tokens = {"humans": sorted(k for k in raw if k != "agents"),
                  "agents": sorted((raw.get("agents") or {}).keys()) if isinstance(raw.get("agents"), dict) else []}
    except (OSError, ValueError, AttributeError):
        tokens = None
    db = Path(os.environ.get("EDP8_DB") or (V8 / ".data" / "edp8.db"))
    humans: list[str] | None = None
    try:
        con = sqlite3.connect(f"file:{db.as_posix()}?mode=ro", uri=True)
        humans = sorted(json.loads(b).get("handle", "").lstrip("@") for (b,) in con.execute("SELECT body FROM participant")
                        if json.loads(b).get("type") == "human")
        con.close()
    except sqlite3.Error:
        pass
    pool_port = int(os.environ.get("EDP_POOL_PORT") or 9301)
    sessions = _get_json(f"http://127.0.0.1:{pool_port}/v1/sessions")
    seats = sorted({s.get("handle") for s in sessions if isinstance(s, dict) and s.get("state") == "active"
                    and s.get("handle")}) if isinstance(sessions, list) else None
    rc, st = _run(["tailscale", "status", "--json"])
    ts = None
    if rc == 0:
        try:
            d = json.loads(st)
            ts = {"backend": d.get("BackendState"), "dns": ((d.get("Self") or {}).get("DNSName") or "").rstrip("."),
                  "cert_domains": d.get("CertDomains") or [], "peers": len(d.get("Peer") or {})}
        except ValueError:
            ts = None
    rc, sv = _run(["tailscale", "serve", "status", "--json"])
    serve = None
    if rc == 0:
        try:
            serve = json.loads(sv or "{}")
        except ValueError:
            serve = None
    ports = {name: int(os.environ.get(var) or dflt) for name, (var, dflt) in PORTS.items()}
    return {"planned": planned, "env": eff, "tokens_path": str(tokens_path), "tokens": tokens, "humans": humans,
            "seats": seats, "tailscale": ts, "serve": serve, "ports": ports, "listeners": listeners()}


# ------------------------------------------------------------------------------------ classifier
# The pure classifier lives in the package (S5: Admin → Remote access shows the same rows); this script
# keeps the host-side fact gathering for `edp.ps1 tailnet check`.
from edp8.tailnet import _loopback, classify, serve_proxies  # noqa: E402,F401


def render(rows: list[dict]) -> str:
    order = {"BLOCKER": 0, "WARN": 1, "OK": 2, "INFO": 3}
    lines = []
    for r in sorted(rows, key=lambda r: order[r["level"]]):
        lines.append(f"{r['level']:<8} {r['area']:<17} {r['text']}" + (f"\n{'':<27}fix: {r['fix']}" if r["fix"] else ""))
    b = sum(r["level"] == "BLOCKER" for r in rows)
    w = sum(r["level"] == "WARN" for r in rows)
    lines.append(f"\n{b} blocker(s), {w} warning(s) - " + ("NOT READY" if b else "ready for `edp.ps1 tailnet apply`"))
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--planned", action="store_true", help="evaluate the env as `edp.ps1 tailnet apply` writes it")
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args(argv)
    try:
        rows = classify(gather(a.planned))
    except Exception as e:  # noqa: BLE001
        print(f"tailnet_readiness: check failed: {e}", file=sys.stderr)
        return 2
    if a.json:
        print(json.dumps({"rows": rows, "blockers": sum(r["level"] == "BLOCKER" for r in rows)}, indent=1))
    else:
        print(render(rows))
    return 1 if any(r["level"] == "BLOCKER" for r in rows) else 0


if __name__ == "__main__":
    sys.exit(main())
