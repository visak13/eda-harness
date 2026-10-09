"""The guest access route matrix (epic-0cec8d1c31 S5; seeded by the S1 spike, report-f1bc7d34da).

Enumerates every REST operation from `app.openapi()["paths"]` (FastAPI >=0.141 includes routers lazily, so
`app.routes` is not the table) plus the hidden (include_in_schema=False) routes, and every MCP tool in
`bundles.ALL_TOOLS`. For each row it records read/write, the objects touched, the role check found statically
in the endpoint source and the guest treatment ENFORCED at runtime: the treatment is read from
`edp8.guest_scope.treatment()`, the same table the shared `actor` dependency applies, so this matrix cannot
drift from what the board does.

- scoped   — readable/writable only inside the guest's member epics (guest_scope: path/query ids 404 outside the
             scope, JSON answers redacted, plus the per-route/board checks named in `why`)
- refused  — a guest gets 403 (authority, admin, seats, models, settings, Code tab …)
- allowed  — carries no epic data (health, own identity/avatar/settings, static contracts)
- unclassified — not in the table: refused at runtime, and `--check` / the route test fail

Output: docs/evidence/e0cec-s5/route-matrix.json and .md.  Run from v8/:  python scripts/guest_route_matrix.py [--check]
"""

from __future__ import annotations

import argparse
import ast
import inspect
import json
import os
import re
import sys
import tempfile
import textwrap
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src" / "edp8"
OUT = ROOT / "docs" / "evidence" / "e0cec-s5"
METHODS = ("get", "post", "put", "patch", "delete")

# role-check patterns found in endpoint source → a short label (all that match are listed)
CHECKS: list[tuple[str, str]] = [
    (r"Depends\(admin\)|dependencies=\[Depends\(admin", "admin header/token"),
    (r"is_admin\(", "is_admin()"),
    (r"_authorize_pool_op\(", "_authorize_pool_op (owner any; architect own epic)"),
    (r"_refuse_non_agent\(", "_refuse_non_agent"),
    (r"Role\.owner|== ?\"owner\"|'owner'", "owner role"),
    (r"Role\.architect", "architect role"),
    (r"Role\.doctor|Depends\(reader\)", "doctor/reader"),
    (r"Role\.qa", "qa role"),
    (r"Role\.expert|topic_actor", "expert/topic scope"),
    (r"\.type ?!= ?\"human\"|\.type ?== ?\"human\"", "human-only"),
    (r"_guard\(", "ui _guard (verified identity)"),
    (r"_me\(", "ui _me (form as_/token verified)"),
    (r"_local\(", "board-host-only (loopback peer)"),
    (r"_verify_expert|expert_session|redeem", "own credential flow"),
    (r"guest_scope\.", "guest_scope (explicit call)"),
    (r"staged.*created_by", "staged→uploader only"),
]
OBJECT_WORDS = ["ticket", "criterion", "doc", "link", "artifact", "message", "gate", "event", "participant",
                "session", "decision", "claim", "lesson", "pain", "workflow", "topic", "settings", "avatar",
                "usage", "fix", "attention", "index", "token", "model", "harness", "service"]


def _isolated_env() -> None:
    for k in [k for k in os.environ if k.startswith("EDP")]:
        del os.environ[k]
    tmp = Path(tempfile.mkdtemp(prefix="guest-matrix-"))
    os.environ.update({"EDP8_TOKENS": str(tmp / "absent.json"), "EDP_POOL_PORT": "1", "EDP8_EMBEDDER": "none",
                       "EDP8_HOME": str(tmp), "EDP8_DATA": str(tmp / "data"), "EDP8_UI": "folio"})


def _norm(path: str) -> str:
    return re.sub(r"\{[^}]+\}", "{}", path)


def _endpoint_index() -> dict[tuple[str, str], dict]:
    """(METHOD, normalised path) → {file, line, name, src} from every route decorator in src/edp8."""
    out: dict[tuple[str, str], dict] = {}
    for f in SRC.rglob("*.py"):
        text = f.read_text(encoding="utf-8")
        try:
            tree = ast.parse(text)
        except SyntaxError:
            continue
        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            for dec in node.decorator_list:
                if not (isinstance(dec, ast.Call) and isinstance(dec.func, ast.Attribute)
                        and dec.func.attr in METHODS and dec.args):
                    continue
                a0 = dec.args[0]
                if isinstance(a0, ast.Constant) and isinstance(a0.value, str):
                    paths = [a0.value]
                elif isinstance(a0, ast.BinOp) and isinstance(a0.right, ast.Constant):  # prefix + "/x"
                    paths = [p + a0.right.value for p in ("/ui", "/ui-legacy")]
                elif isinstance(a0, ast.JoinedStr):  # ui_router(prefix=…): f"{prefix}/x"
                    tail = "".join(v.value if isinstance(v, ast.Constant) else "{}" for v in a0.values)
                    paths = [tail.replace("{}", p, 1) for p in ("/ui", "/ui-legacy")] if tail.startswith("{}") \
                        else [tail]
                else:
                    continue
                src = ast.get_source_segment(text, node) or ""
                deco = ast.get_source_segment(text, dec) or ""
                for p in paths:
                    out.setdefault((dec.func.attr.upper(), _norm(p)), {
                        "file": str(f.relative_to(ROOT)).replace("\\", "/"), "line": node.lineno,
                        "name": node.name, "src": deco + "\n" + src})
    return out


def _checks(src: str, path: str) -> list[str]:
    found = [label for rx, label in CHECKS if re.search(rx, src)]
    if path.startswith("/v1/admin"):
        found.insert(0, "admin router gate")
    if re.search(r"board\.\w+\(\s*(a|actor)\s*[,)]|actor=a\b", src):
        found.append("board-side (actor passed in)")
    if not found:
        found = ["authenticated actor only" if re.search(r"Depends\((actor|topic_actor)\)", src) else "none"]
    return found


def _objects(src: str, path: str) -> list[str]:
    low = (src + " " + path).lower()
    return [w for w in OBJECT_WORDS if re.search(rf"\b{w}s?\b|\"{w}\"|{w}_", low)]


def _guest(method: str, path: str) -> tuple[str, str]:
    from edp8 import guest_scope
    return guest_scope.treatment(method, path)


_READ_POSTS = re.compile(r"/v1/workflows/(card-preview|diff|dryrun|validate)$")


def rest_rows(app) -> list[dict]:
    idx = _endpoint_index()
    rows = []
    for path, ops in app.openapi()["paths"].items():
        for m in ops:
            if m not in METHODS:
                continue
            M = m.upper()
            ep = idx.get((M, _norm(path)), {})
            src = ep.get("src", "")
            treat, why = _guest(M, path)
            rows.append({"kind": "rest", "method": M, "path": path,
                         "rw": "read" if M == "GET" or _READ_POSTS.search(path) else "write",
                         "objects": _objects(src, path), "current_check": _checks(src, path),
                         "where": f"{ep['file']}:{ep['line']} {ep['name']}" if ep else "?",
                         "guest": treat, "guest_why": why})
    return rows


def hidden_rows(app) -> list[dict]:
    """include_in_schema=False routes and mounts (openapi omits them): the SPA shell and its assets."""
    seen = {(r["method"], r["path"]) for r in rest_rows(app)}
    rows = []
    for r in app.routes:
        path = getattr(r, "path", None)
        methods = sorted(getattr(r, "methods", None) or ["GET"])
        for M in methods:
            if path is None or M == "HEAD" or (M, path) in seen:
                continue
            treat, why = _guest(M, path)
            rows.append({"kind": "hidden", "method": M, "path": path, "rw": "read", "objects": [],
                         "current_check": ["none (static)"], "where": type(r).__name__,
                         "guest": treat, "guest_why": why})
    return rows


def _client_paths() -> dict[str, tuple[str, str]]:
    """BoardClient method → (METHOD, normalised path), from its `self._request("M", "/path")` calls."""
    tree = ast.parse((SRC / "client.py").read_text(encoding="utf-8"))
    out: dict[str, tuple[str, str]] = {}
    for cls in [n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == "BoardClient"]:
        for fn in [n for n in cls.body if isinstance(n, ast.FunctionDef)]:
            for call in [n for n in ast.walk(fn) if isinstance(n, ast.Call)]:
                f = call.func
                if (isinstance(f, ast.Attribute) and f.attr in METHODS and call.args
                        and isinstance(call.args[0], ast.Constant) and str(call.args[0].value).startswith("/v1")):
                    out.setdefault(fn.name, (f.attr.upper(), _norm(call.args[0].value)))  # transport.post("/v1/…")
                if isinstance(f, ast.Attribute) and f.attr == "_request" and len(call.args) >= 2:
                    m, p = call.args[0], call.args[1]
                    if isinstance(m, ast.Constant):
                        if isinstance(p, ast.Constant):
                            path = p.value
                        elif isinstance(p, ast.JoinedStr):
                            path = "".join(v.value if isinstance(v, ast.Constant) else "{x}" for v in p.values)
                        else:
                            continue
                        out.setdefault(fn.name, (m.value.upper(), _norm(path)))
    return out


def tool_rows(rest: list[dict]) -> list[dict]:
    from edp8 import bundles
    cpaths = _client_paths()
    by_route = {(r["method"], _norm(r["path"])): r for r in rest}
    mod_src = inspect.getsource(bundles)
    helpers = {n.name: ast.get_source_segment(mod_src, n) or "" for n in ast.parse(mod_src).body
               if isinstance(n, ast.FunctionDef)}
    rows = []
    for name, td in sorted(bundles.ALL_TOOLS.items()):
        src = inspect.getsource(td.handler)
        seen_fns, calls, frontier = {td.handler.__name__}, set(), [src]
        for _ in range(3):  # the handler and two levels of module helpers it calls
            nxt = []
            for s in frontier:
                calls |= set(re.findall(r"(?:get_client\(\)|\bc|\bclient|\bcl)\.(\w+)\(", s))
                for h in re.findall(r"\b(_\w+)\(", s):
                    if h in helpers and h not in seen_fns:
                        seen_fns.add(h)
                        nxt.append(helpers[h])
            frontier = nxt
        routes = sorted({cpaths[c] for c in calls if c in cpaths})
        matched = [by_route[r] for r in routes if r in by_route]
        treats = {m["guest"] for m in matched}
        pool = "pool_adapter" in src or "_pool_caller_check" in "".join(helpers.get(f, "") for f in seen_fns)
        derived = ("refused" if pool or "refused" in treats or "unclassified" in treats or not matched
                   else "scoped" if "scoped" in treats else "allowed")
        from edp8 import guest_scope
        guest = guest_scope.tool_treatment(name)
        rows.append({"kind": "mcp", "tool": name, "bundle": td.bundle,
                     "rest": [f"{m} {p}" for m, p in routes],
                     "rw": "write" if any(m["rw"] == "write" for m in matched) else "read",
                     "objects": sorted({o for m in matched for o in m["objects"]}),
                     "current_check": sorted({c for m in matched for c in m["current_check"]})
                     + (["_pool_caller_check (owner; architect own epic)"] if pool else []),
                     "guest": guest, "derived": derived,
                     "guest_why": ("a tool is a BoardClient REST call made as the caller: the REST gate enforces "
                                   "it" if matched else "no board REST route (local/pool): refused unless listed")})
    return rows


def render_md(rows: list[dict]) -> str:
    rest = [r for r in rows if r["kind"] in ("rest", "hidden")]
    tools = [r for r in rows if r["kind"] == "mcp"]
    count = lambda rs, t: sum(1 for r in rs if r["guest"] == t)  # noqa: E731
    lines = [
        "# Guest route matrix (epic-0cec8d1c31 S5, s-d2f98230cb)", "",
        "Generated by `v8/scripts/guest_route_matrix.py` from `app.openapi()[\"paths\"]` (+ hidden routes) and "
        "`bundles.ALL_TOOLS`. `guest` is the treatment the board ENFORCES (read from `edp8.guest_scope.treatment`, "
        "the table the shared actor dependency applies); `current_check` is found statically in the endpoint "
        "source. For tools, `derived` is the strictest treatment of the REST routes the tool calls.", "",
        f"REST operations: {len([r for r in rest if r['kind'] == 'rest'])} (+{len(rest) - len([r for r in rest if r['kind'] == 'rest'])} hidden) — "
        f"scoped {count(rest, 'scoped')}, refused {count(rest, 'refused')}, allowed {count(rest, 'allowed')}, "
        f"unclassified {count(rest, 'unclassified')}.",
        f"MCP tools: {len(tools)} — scoped {count(tools, 'scoped')}, refused {count(tools, 'refused')}, "
        f"allowed {count(tools, 'allowed')}.", "",
        "## REST", "",
        "| method | path | r/w | objects | current check | guest | why | where |",
        "|---|---|---|---|---|---|---|---|"]
    for r in rest:
        lines.append(f"| {r['method']} | `{r['path']}` | {r['rw']} | {', '.join(r['objects'])} | "
                     f"{'; '.join(r['current_check'])} | **{r['guest']}** | {r['guest_why']} | {r['where']} |")
    lines += ["", "## MCP tools", "", "| tool | bundle | REST it calls | r/w | current check | guest | derived |",
              "|---|---|---|---|---|---|---|"]
    for r in tools:
        lines.append(f"| `{r['tool']}` | {r['bundle']} | {'<br>'.join(r['rest']) or '—'} | {r['rw']} | "
                     f"{'; '.join(r['current_check']) or '—'} | **{r['guest']}** | {r['derived']} |")
    return "\n".join(lines) + "\n"


def build() -> list[dict]:
    _isolated_env()
    sys.path.insert(0, str(ROOT / "src"))
    from edp8.board import Board
    from edp8.service import create_app
    from edp8.store import Store
    app = create_app(Board(Store(":memory:")), admin_token="matrix")
    rest = rest_rows(app)
    return rest + hidden_rows(app) + tool_rows(rest)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--check", action="store_true", help="exit 1 if any route/tool is unclassified")
    args = ap.parse_args()
    rows = build()
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "route-matrix.json").write_text(json.dumps(rows, indent=1, ensure_ascii=False), encoding="utf-8")
    (OUT / "route-matrix.md").write_text(render_md(rows), encoding="utf-8")
    bad = [r for r in rows if r["guest"] == "unclassified"]
    print(textwrap.dedent(f"""\
        rows: {len(rows)} (rest {sum(r['kind'] == 'rest' for r in rows)}, hidden {sum(r['kind'] == 'hidden' for r in rows)}, mcp {sum(r['kind'] == 'mcp' for r in rows)})
        unclassified: {len(bad)}"""))
    for r in bad:
        print("  ", r.get("method", ""), r.get("path", r.get("tool")))
    return 1 if (args.check and bad) else 0


if __name__ == "__main__":
    raise SystemExit(main())
