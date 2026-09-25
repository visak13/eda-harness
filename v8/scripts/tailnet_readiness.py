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
def _loopback(addr: str) -> bool:
    try:
        return ipaddress.ip_address(addr.split("%")[0]).is_loopback
    except ValueError:
        return addr in ("localhost",)


def serve_proxies(serve: dict) -> list[tuple[str, str]]:
    """(host:port, proxy target) for every web handler in a `tailscale serve status --json` config."""
    out = []
    for hp, web in (serve.get("Web") or {}).items():
        for _path, h in ((web or {}).get("Handlers") or {}).items():
            out.append((hp, (h or {}).get("Proxy") or (h or {}).get("Path") or (h or {}).get("Text") or "?"))
    return out


def classify(f: dict) -> list[dict]:
    """Pure: facts -> rows {level: BLOCKER|WARN|OK|INFO, area, text, fix}. No row ever carries a secret."""
    rows: list[dict] = []

    def row(level, area, text, fix=""):
        rows.append({"level": level, "area": area, "text": text, "fix": fix})

    planned = f["planned"]
    env = f["env"]
    ts = f.get("tailscale")
    name = (ts or {}).get("dns") or ""
    want_url = f"https://{name}" if name else ""

    # env: admin token, public URL, bind host (and a persistent real env that would beat .env)
    admin = env["EDP8_ADMIN_TOKEN"]["value"]
    if (admin or DEFAULT_ADMIN) == DEFAULT_ADMIN and not planned:
        row("BLOCKER", "admin token", "EDP8_ADMIN_TOKEN is unset/'dev': the board refuses a public start",
            "`.\\edp.ps1 tailnet apply` generates one into v8/.env (never printed)")
    else:
        row("OK", "admin token", "non-default" if (admin or DEFAULT_ADMIN) != DEFAULT_ADMIN
            else "default now; apply generates a non-default one")
    row("INFO", "admin token", "consumers board, bootstrap, MCP proxy, supervisor read it at start: "
        "restart board + mcp + supervisor together (apply does)")
    host = env["EDP8_HOST"]["value"]
    if planned:
        row("OK", "bind", "apply pins EDP8_HOST=127.0.0.1 (board + broker stay loopback)")
    elif not host:
        row("BLOCKER", "bind", "EDP8_HOST is unset: public mode binds the board AND the broker to 0.0.0.0",
            "pin EDP8_HOST=127.0.0.1 (apply does)")
    elif not _loopback(host):
        row("BLOCKER", "bind", f"EDP8_HOST={host} is not loopback", "EDP8_HOST=127.0.0.1")
    else:
        row("OK", "bind", f"EDP8_HOST={host}")
    url = env["EDP8_PUBLIC_URL"]["value"]
    if url and want_url and url.rstrip("/") != want_url:
        row("BLOCKER", "public url", f"EDP8_PUBLIC_URL={url} is not the tailnet name {want_url}",
            f"EDP8_PUBLIC_URL={want_url}")
    elif url:
        row("OK", "public url", f"EDP8_PUBLIC_URL={url}")
    else:
        row("INFO", "public url", f"unset (trusted mode); apply sets {want_url or 'https://<tailnet name>'}")
    for k in KEYS:
        for scope, v in env[k]["persistent"].items():
            shown = "<set>" if k == "EDP8_ADMIN_TOKEN" else v
            row("BLOCKER", "real env", f"{k} is set in the {scope} environment ({shown}); it beats v8/.env, "
                "so apply/remove cannot control it", f"remove it: [Environment]::SetEnvironmentVariable('{k}', $null, '{scope.title()}')")

    # credentials: the board's own public start gate, humans, live seats
    tok = f.get("tokens")
    if tok is None:
        row("BLOCKER", "tokens.json", f"{f['tokens_path']} is missing or invalid: public mode refuses to start")
    else:
        if not tok["humans"]:
            row("BLOCKER", "tokens.json", "no human credentials: the board refuses a public start")
        if not tok["agents"]:
            row("BLOCKER", "tokens.json", "no agent credentials: the board refuses a public start")
        if tok["humans"] and tok["agents"]:
            row("OK", "tokens.json", f"{len(tok['humans'])} human(s), {len(tok['agents'])} agent secret(s)")
        if f.get("humans") is None:
            row("WARN", "humans", "board DB unreadable; humans without a token not listed")
        else:
            missing = [h for h in f["humans"] if h not in tok["humans"]]
            for h in missing:
                row("WARN", "humans", f"human '{h}' has no token: cannot sign in (header-only is refused)",
                    "mint one if they are a real person; a stale participant needs nothing")
            if not missing:
                row("OK", "humans", "every human on the board has a token")
        seats = f.get("seats")
        if seats is None:
            row("WARN", "seats", "pool unreachable: live seats not checked")
        else:
            bad = [s for s in seats if s not in tok["agents"]]
            for s in bad:
                row("BLOCKER", "seats", f"live seat {s} has no minted token: its MCP calls, feed_driver and "
                    "consult 401 after the switch", "close it, or reap + respawn it after the spawn-mint fix "
                    "(2ffb89d) is live (board + mcp restarted)")
            if not bad:
                row("OK", "seats", f"all {len(seats)} live seat(s) hold a minted token")
    row("INFO", "loopback callers", "MCP proxy :9402 forwards each seat's X-Participant + X-Token (401 only for "
        "the seats above); feed_driver sends EDP8_TOKEN; pool and broker never call the board; supervisor "
        "uses X-Admin (restart it with the new admin token)")
    row("INFO", "loopback callers", "MCP single-host HTTP upload switches itself off when EDP8_PUBLIC_URL is in "
        "the proxy's env (http_upload.py)")

    # tailnet: running, HTTPS certificates for this node's name
    if ts is None:
        row("BLOCKER", "tailscale", "`tailscale status --json` failed: tailscale not installed or not running")
    else:
        if ts["backend"] != "Running":
            row("BLOCKER", "tailscale", f"backend state {ts['backend']}", "tailscale up")
        else:
            row("OK", "tailscale", f"running as {name}; {ts['peers']} peer(s)")
        if name and name in ts["cert_domains"]:
            row("OK", "certificates", f"tailnet HTTPS certificates on for {name}")
        else:
            row("BLOCKER", "certificates", "tailnet HTTPS certificates are off (CertDomains empty)",
                "owner: admin console > DNS > enable HTTPS Certificates")

    # serve config: none yet, or exactly 443 -> the loopback board; never Funnel, never code-server
    serve = f.get("serve")
    board, code = f["ports"]["board"], f["ports"]["code-server"]
    want = f"http://127.0.0.1:{board}"
    if serve is None:
        row("WARN", "serve", "`tailscale serve status --json` failed; serve config not checked")
    elif not serve:
        row("OK", "serve", f"no serve config yet; apply adds https:443 -> {want}")
    else:
        for hp, target in serve_proxies(serve):
            t = target.rstrip("/")
            if re.search(rf":{code}\b", t):
                row("BLOCKER", "serve", f"{hp} proxies code-server ({t}): an unauthenticated shell on the tailnet",
                    "tailscale serve reset")
            elif t in (want, f"http://localhost:{board}") and hp.endswith(":443"):
                row("OK", "serve", f"{hp} -> {t}")
            else:
                row("BLOCKER", "serve", f"{hp} -> {t} is not the expected https:443 -> {want}", "tailscale serve reset")
        for port, tcp in (serve.get("TCP") or {}).items():
            fwd = (tcp or {}).get("TCPForward")
            if fwd:
                row("BLOCKER", "serve", f"tcp:{port} is a raw TCP forward to {fwd} (no TLS, bypasses the https front)",
                    "tailscale serve reset")
        for hp, on in (serve.get("AllowFunnel") or {}).items():
            if on:
                row("BLOCKER", "serve", f"Funnel is on for {hp}: the board would face the public internet",
                    "tailscale funnel reset")

    # listeners: every fleet port on loopback only
    ls = f.get("listeners") or {}
    for svc, port in f["ports"].items():
        addrs = ls.get(port) or []
        wide = [a for a in addrs if not _loopback(a)]
        if wide:
            row("BLOCKER", "listen", f"{svc} :{port} listens on {', '.join(sorted(set(wide)))}",
                "bind it to 127.0.0.1")
        elif addrs:
            row("OK", "listen", f"{svc} :{port} on {', '.join(sorted(set(addrs)))} only")
        else:
            row("INFO", "listen", f"{svc} :{port} not listening")
    return rows


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
