"""Tailnet public mode (design-e963c656f5 §4.8 Remote access; design-10b21760d9 §4.3 shape): the board stays on
127.0.0.1, `tailscale serve --https=443 http://127.0.0.1:<port>` terminates TLS on the tailnet only, and
EDP8_PUBLIC_URL=https://<tailnet name> turns on public mode's fail-closed token rules.

`classify` is the pure readiness classifier (moved here from scripts/tailnet_readiness.py, which imports
it); `gather` collects the same facts from this install's settings, so Admin → Remote access and
`edp.ps1 tailnet check` show the same rows. `apply`/`remove` change tailscale serve and config.toml; they
never restart anything (the admin restarts board + mcp from Admin → Services) and never print a token.
Every tailscale call goes through `_run`, the seam tests replace.
"""

from __future__ import annotations

import ipaddress
import json
import re
import subprocess
from pathlib import Path
from typing import Any

from . import settings

KEYS = ("EDP8_ADMIN_TOKEN", "EDP8_PUBLIC_URL", "EDP8_HOST")
DEFAULT_ADMIN = "dev"
#: every listener that must stay loopback after the switch
PORT_SETTINGS = {"board": "EDP8_PORT", "mcp": "EDP8_MCP_PORT", "pool": "EDP_POOL_PORT", "broker": "EDP_BROKER_PORT",
                 "code-server": "EDP_CODE_PORT"}


class TailnetError(RuntimeError):
    """apply/remove refused or failed; the message is one plain line (never a secret)."""


def _run(cmd: list[str]) -> tuple[int, str]:
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=30, stdin=subprocess.DEVNULL)
        return p.returncode, p.stdout or p.stderr
    except (OSError, subprocess.TimeoutExpired) as e:
        return 127, str(e)


def _tailscale() -> str:
    from edp_contracts.toolpath import find_tool
    return find_tool("tailscale") or "tailscale"


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


# ------------------------------------------------------------------------------------ facts (this install)

def tailscale_facts() -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    """(status, serve config) from the tailscale CLI; None for a call that failed."""
    ts = serve = None
    rc, out = _run([_tailscale(), "status", "--json"])
    if rc == 0:
        try:
            d = json.loads(out)
            ts = {"backend": d.get("BackendState"), "dns": ((d.get("Self") or {}).get("DNSName") or "").rstrip("."),
                  "cert_domains": d.get("CertDomains") or [], "peers": len(d.get("Peer") or {})}
        except ValueError:
            ts = None
    rc, out = _run([_tailscale(), "serve", "status", "--json"])
    if rc == 0:
        try:
            serve = json.loads(out or "{}")
        except ValueError:
            serve = None
    return ts, serve


def listeners() -> dict[int, list[str]]:
    """port -> local addresses in LISTEN state (psutil; {} when the OS will not say)."""
    out: dict[int, list[str]] = {}
    try:
        import psutil
        for c in psutil.net_connections(kind="tcp"):
            if c.status == psutil.CONN_LISTEN and c.laddr:
                out.setdefault(int(c.laddr.port), []).append(str(c.laddr.ip))
    except Exception:  # noqa: BLE001 — macOS without root: listeners unknown, the classifier says INFO
        return {}
    return out


def _admin_token_value() -> str | None:
    try:
        return settings.admin_token()
    except settings.SettingsError:
        return None


def gather(*, planned: bool, humans: list[str] | None, seats: list[str] | None) -> dict[str, Any]:
    env: dict[str, dict[str, Any]] = {}
    for k in KEYS:
        val = _admin_token_value() if k == "EDP8_ADMIN_TOKEN" else settings.get(k)
        env[k] = {"value": val, "source": settings.source(k), "persistent": {}}
    tokens_path = Path(settings.get("EDP8_TOKENS"))
    try:
        raw = json.loads(tokens_path.read_text(encoding="utf-8"))
        tokens = {"humans": sorted(k for k in raw if k != "agents"),
                  "agents": sorted((raw.get("agents") or {}).keys()) if isinstance(raw.get("agents"), dict) else []}
    except (OSError, ValueError, AttributeError):
        tokens = None
    ts, serve = tailscale_facts()
    ports = {name: int(settings.get(var)) for name, var in PORT_SETTINGS.items()}
    return {"planned": planned, "env": env, "tokens_path": str(tokens_path), "tokens": tokens, "humans": humans,
            "seats": seats, "tailscale": ts, "serve": serve, "ports": ports, "listeners": listeners()}


def summary(f: dict[str, Any], rows: list[dict]) -> dict[str, Any]:
    name = (f.get("tailscale") or {}).get("dns") or ""
    return {"tailscale": f.get("tailscale"), "serve": f.get("serve"),
            "serve_proxies": [{"from": a, "to": b} for a, b in serve_proxies(f.get("serve") or {})],
            "public_url": f["env"]["EDP8_PUBLIC_URL"]["value"], "tailnet_url": f"https://{name}" if name else None,
            "public_mode": bool(f["env"]["EDP8_PUBLIC_URL"]["value"]), "rows": rows,
            "blockers": sum(r["level"] == "BLOCKER" for r in rows)}


# ------------------------------------------------------------------------------------ apply / remove

def apply(f: dict[str, Any], *, force: bool = False) -> dict[str, Any]:
    """Public mode: fail-closed credentials check, `tailscale serve` https:443 -> the loopback board, then
    config.toml gets EDP8_PUBLIC_URL=https://<tailnet name> and EDP8_HOST=127.0.0.1. `force` passes the
    readiness BLOCKERs, never the fail-closed credentials check (the board would refuse to start)."""
    from .service import public_startup_error
    from .setup import write_config

    for k in ("EDP8_PUBLIC_URL", "EDP8_HOST"):
        if f["env"][k]["source"] == "env":
            raise TailnetError(f"{k} is set by the environment; unset it first (config.toml cannot override it)")
    err = public_startup_error(_admin_token_value(), Path(f["tokens_path"]))
    if err:
        raise TailnetError(err)
    ts = f.get("tailscale")
    name = (ts or {}).get("dns") or ""
    if not ts or ts.get("backend") != "Running" or not name:
        raise TailnetError("tailscale is not running on this machine (or reports no DNS name): `tailscale up`")
    rows = classify({**f, "planned": True})
    blockers = [r for r in rows if r["level"] == "BLOCKER"]
    if blockers and not force:
        raise TailnetError("not ready: " + "; ".join(f"{r['area']}: {r['text']}" for r in blockers))
    port = f["ports"]["board"]
    rc, out = _run([_tailscale(), "serve", "--bg", "--https=443", f"http://127.0.0.1:{port}"])
    if rc != 0:
        raise TailnetError(f"tailscale serve exited {rc}: {out.strip()[:300]}; nothing else changed")
    url = f"https://{name}"
    write_config({"network.public_url": url, "board.host": "127.0.0.1"})
    return {"public_url": url, "serve": f"https:443 -> http://127.0.0.1:{port}", "restart_required": ["board", "mcp"],
            "forced_past": [r["text"] for r in blockers]}


def remove(f: dict[str, Any]) -> dict[str, Any]:
    """Trusted mode again: close the tailnet front first (`tailscale serve reset`), then drop
    EDP8_PUBLIC_URL from config.toml."""
    from .setup import write_config

    if f["env"]["EDP8_PUBLIC_URL"]["source"] == "env":
        raise TailnetError("EDP8_PUBLIC_URL is set by the environment; unset it there")
    rc, out = _run([_tailscale(), "serve", "reset"])
    if rc != 0:
        raise TailnetError(f"tailscale serve reset exited {rc}: {out.strip()[:300]}; config.toml unchanged")
    write_config({}, ["network.public_url"])
    return {"public_url": None, "restart_required": ["board", "mcp"]}
