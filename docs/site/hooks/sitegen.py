"""Generated pages of the Heronry site (design-e963c656f5 §4.15): the reference, the download block and the
brand values, each read from the one place the product declares it, so the site cannot drift.

Every function returns Markdown (or data) and writes nothing; `heronry_site.py` (the mkdocs hook) adds the
results as generated files at build time. Sources:

- CLI         `edp8.cli.COMMANDS` (the table `heronry help` prints)
- settings    `edp_contracts.settings.all_settings()` (the S1 registry; callable defaults are described by
              their `default_doc`, never resolved, so no build machine's paths reach the site)
- REST API    `edp8.service.create_app().openapi()`, in a child process on a throwaway home
- MCP tools   `edp8.bundles.ALL_TOOLS` descriptions and `ROLE_BUNDLES`
- workflow    `edp8.workflow.WorkflowDef` (the S13 definition schema)
- models      `edp8.model_catalog.MODEL_FIELD_DOCS` (the S12 catalog row fields)
- downloads   the GitHub Releases API `latest` for `edp8.brand.REPO_SLUG`, or a release JSON fixture
"""
from __future__ import annotations

import html
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

# ----------------------------------------------------------------------------- helpers


def _flat(text: Any) -> str:
    s = "" if text is None else str(text)
    return " ".join(s.split()).replace("|", "\\|")


def _cell(text: Any) -> str:
    """One Markdown table cell: no newlines, pipes escaped, and `<…>` outside code spans shown as text (a doc line
    like "<data>/models" is a placeholder, not HTML)."""
    parts = _flat(text).split("`")
    return "`".join(p if i % 2 else p.replace("<", "&lt;").replace(">", "&gt;") for i, p in enumerate(parts))


def _code(text: Any) -> str:
    s = _flat(text)
    return f"`{s}`" if s else ""


def _table(head: list[str], rows: list[list[str]]) -> str:
    out = ["| " + " | ".join(head) + " |", "|" + "---|" * len(head)]
    out += ["| " + " | ".join(r) + " |" for r in rows]
    return "\n".join(out)


def _slug(text: str) -> str:
    return "".join(c if c.isalnum() else "-" for c in text.lower()).strip("-")


def _h2(title: str) -> str:
    """A section heading with an explicit id, so the in-page index links cannot miss (attr_list)."""
    return f"## {title} {{ #{_slug(title)} }}"


# ----------------------------------------------------------------------------- brand


def brand() -> dict[str, str]:
    from edp8 import brand as b
    return {"product_name": b.PRODUCT_NAME, "cli_name": b.CLI_NAME, "desktop_app_name": b.DESKTOP_APP_NAME,
            "tagline": b.TAGLINE, "repo_slug": b.REPO_SLUG, "repo_url": b.REPO_URL,
            "releases_url": b.RELEASES_URL, "download_url": b.DOWNLOAD_URL, "video_url": b.VIDEO_URL,
            "site_url": b.SITE_URL, "asset_dir": b.ASSET_DIR}


def version() -> str:
    from importlib.metadata import version as _v
    return _v("edp8")


# ----------------------------------------------------------------------------- CLI


def cli_md() -> str:
    from edp8 import cli
    name = brand()["cli_name"]
    parts = [f"# Command line: `{name}`", "",
             f"Generated at build from the command table `{name} help` prints. `{name} <command> [args]`; "
             f"`edp8` is an alias of `{name}`.", ""]
    parts.append(_table(["Command", "What it does"],
                        [[f"[`{name} {c.usage}`](#{_slug(c.name)})", _cell(c.summary)] for c in cli.COMMANDS]))
    for c in cli.COMMANDS:
        parts += ["", _h2(c.name), "", f"```\n{name} {c.usage}\n```", "", c.summary.rstrip(".") + "."]
        if c.flags:
            parts += ["", _table(["Flag", "Meaning"], [[_code(f), _cell(h)] for f, h in c.flags])]
    return "\n".join(parts) + "\n"


# ----------------------------------------------------------------------------- settings


def _default_text(s: Any) -> str:
    if s.secret:
        return "(secret)"
    if callable(s.default):
        return _code(s.default_doc) if s.default_doc else "(derived)"
    if s.default is None:
        return "(unset)"
    if isinstance(s.default, (list, tuple, dict)):
        return _code(json.dumps(s.default))
    return _code(json.dumps(s.default) if isinstance(s.default, bool) else s.default)


#: settings groups the reference leaves out: the brand values name the product; they are `internal`, not a user
#: knob (owner m-da9a2ae62f)
SETTINGS_OMIT_GROUPS = frozenset({"brand"})


def settings_md() -> str:
    from edp_contracts import settings
    rows_by_group: dict[str, list[Any]] = {}
    for s in settings.all_settings():
        if s.group not in SETTINGS_OMIT_GROUPS:
            rows_by_group.setdefault(s.group, []).append(s)
    total = sum(len(v) for v in rows_by_group.values())
    parts = ["# Settings", "",
             f"Generated at build from the settings registry ({total} settings). Each value resolves "
             "**environment variable > `config.toml` key > default**; Admin → Settings shows the `basic` ones, "
             "the `advanced` ones behind *Show advanced*, and never the `internal` ones. "
             "`restart` names the service a change needs restarted.", ""]
    parts.append(" · ".join(f"[{g}](#{_slug(g)})" for g in rows_by_group))
    for group, rows in rows_by_group.items():
        parts += ["", _h2(group), ""]
        body = []
        for s in rows:
            what = s.doc
            if s.choices:
                what += " Choices: " + ", ".join(f"`{c}`" for c in s.choices) + "."
            if s.unit:
                what += f" Unit: {s.unit}."
            flags = [s.tier]
            if s.env_only:
                flags.append("env only")
            if s.restart_required and s.restart_required != "none":
                flags.append(f"restart {s.restart_required}")
            body.append([_code(s.env), "" if s.env_only else _code(s.key), _cell(s.type), _default_text(s),
                         _cell(what), _cell(", ".join(flags))])
        parts.append(_table(["Env", "config.toml key", "Type", "Default", "What it does", "Tier"], body))
    return "\n".join(parts) + "\n"


# ----------------------------------------------------------------------------- REST API

_OPENAPI_CHILD = r"""
import json, sys
from edp8.service import create_app
print(json.dumps(create_app().openapi()))
"""
#: env the child drops: it must never see the fleet's home, tokens, pool or public mode
_CHILD_DROP = ("EDP_HOME", "EDP8_HOME", "EDP8_RUN_DIR", "EDP8_DATA", "EDP8_DB", "EDP_CONFIG_DIR", "EDP_AGENT_HOME",
               "EDP_POOL_AGENT_HOME", "EDP8_PUBLIC_URL", "EDP8_HOST", "EDP_POOL_URL", "EDP8_POOL_WATCH",
               "EDP8_TOKENS", "EDP8_TOKEN", "EDP8_BOARD_URL")


def openapi() -> dict[str, Any]:
    """The board's OpenAPI document, from a child process on a throwaway home (create_app opens a DB and may
    start watchers; none of it may touch a running install)."""
    with tempfile.TemporaryDirectory(prefix="heronry-site-") as tmp:
        env = {k: v for k, v in os.environ.items() if k not in _CHILD_DROP}
        env.update({"EDP8_HOME": tmp, "EDP_HOME": tmp, "EDP8_DB": str(Path(tmp) / "site.db"),
                    "EDP8_TOKENS": str(Path(tmp) / "tokens.json"), "EDP8_EMBEDDER": "none", "EDP_DEV": "1",
                    "PYTHONIOENCODING": "utf-8"})
        out = subprocess.run([sys.executable, "-c", _OPENAPI_CHILD], env=env, cwd=tmp, capture_output=True,
                             text=True, encoding="utf-8", timeout=300)
        if out.returncode != 0:
            raise RuntimeError(f"openapi child failed ({out.returncode}): {out.stderr[-2000:]}")
        line = [ln for ln in out.stdout.splitlines() if ln.startswith("{")][-1]
        return json.loads(line)


_METHODS = ("get", "post", "put", "patch", "delete")


def rest_md(doc: dict[str, Any] | None = None) -> str:
    doc = doc if doc is not None else openapi()
    by_area: dict[str, list[list[str]]] = {}
    count = 0
    for path, ops in sorted(doc.get("paths", {}).items()):
        for m in _METHODS:
            op = ops.get(m)
            if op is None:
                continue
            count += 1
            seg = [p for p in path.split("/") if p and not p.startswith("{")]
            area = "/".join(seg[:2]) if seg[:1] == ["v1"] else (seg[0] if seg else "/")
            if seg[:2] == ["v1", "admin"] and len(seg) > 2:
                area = "/".join(seg[:3])
            summary = op.get("summary") or ""
            desc = (op.get("description") or "").strip().split("\n\n")[0]
            by_area.setdefault(area, []).append([f"`{m.upper()}`", _code(path), _cell(desc or summary)])
    parts = ["# REST API", "",
             f"Generated at build from the board's OpenAPI document ({count} operations). The full machine-readable "
             "schema is [openapi.json](openapi.json). Agent seats call the same API through the "
             "[MCP tools](mcp-tools.md); a running board also serves it at `/openapi.json`.", ""]
    parts.append(" · ".join(f"[{a}](#{_slug(a)})" for a in sorted(by_area)))
    for area in sorted(by_area):
        parts += ["", _h2(area), "", _table(["Method", "Path", "What it does"], by_area[area])]
    return "\n".join(parts) + "\n"


# ----------------------------------------------------------------------------- MCP tools


def mcp_md() -> str:
    from edp8 import bundles
    tools = dict(sorted(bundles.ALL_TOOLS.items()))
    roles = {name: sorted(r for r, names in bundles.ROLE_BUNDLES.items() if name in names) for name in tools}
    by_bundle: dict[str, list[Any]] = {}
    for t in tools.values():
        by_bundle.setdefault(t.bundle, []).append(t)
    parts = ["# MCP tools", "",
             f"Generated at build from the tool definitions every seat's MCP server advertises ({len(tools)} tools). "
             "A seat sees only its role's bundle; the roles column lists the built-in roles that get each tool "
             "(a custom workflow role picks its own in the [Design tab](../docs/design-tab.md)).", ""]
    parts.append(" · ".join(f"[{b}](#{_slug(b)})" for b in sorted(by_bundle)))
    for b in sorted(by_bundle):
        parts += ["", _h2(b), ""]
        for t in by_bundle[b]:
            parts += [f"### `{t.name}`", "", t.description, ""]
            props = t.input_schema.get("properties", {})
            req = set(t.input_schema.get("required", []))
            if props:
                rows = []
                for arg, spec in props.items():
                    rows.append([_code(arg), _cell(_type_of(spec)), "yes" if arg in req else "", _cell(spec.get("description", ""))])
                parts += [_table(["Argument", "Type", "Required", "Meaning"], rows), ""]
            if roles[t.name]:
                parts += ["Roles: " + ", ".join(roles[t.name]), ""]
    return "\n".join(parts) + "\n"


# ----------------------------------------------------------------------------- workflow schema


def _type_of(spec: dict[str, Any]) -> str:
    if "$ref" in spec:
        return spec["$ref"].rsplit("/", 1)[-1]
    if "anyOf" in spec:
        return " or ".join(_type_of(s) for s in spec["anyOf"])
    if "enum" in spec:
        return "one of " + ", ".join(map(str, spec["enum"]))
    if "const" in spec:
        return json.dumps(spec["const"])
    t = spec.get("type", "any")
    if t == "array":
        return f"list of {_type_of(spec.get('items', {}))}"
    if t == "object" and "additionalProperties" in spec and isinstance(spec["additionalProperties"], dict):
        return f"map of {_type_of(spec['additionalProperties'])}"
    return str(t)


def _schema_tables(schema: dict[str, Any], root_title: str) -> list[str]:
    defs = dict(schema.get("$defs", {}))
    order = [(root_title, schema)] + sorted(defs.items())
    parts: list[str] = []
    for name, d in order:
        parts += ["", f"## {name}", ""]
        if d.get("description"):
            parts += [" ".join(d["description"].split()), ""]
        req = set(d.get("required", []))
        rows = []
        for field, spec in d.get("properties", {}).items():
            default = "" if field in req else _code(json.dumps(spec["default"])) if "default" in spec else ""
            rows.append([_code(field), _cell(_type_of(spec)), "yes" if field in req else "", default])
        parts.append(_table(["Field", "Type", "Required", "Default"], rows))
    return parts


def workflow_md() -> str:
    from edp8 import workflow
    schema = workflow.WorkflowDef.model_json_schema(by_alias=True)
    parts = ["# Workflow definition schema", "",
             f"Generated at build from the workflow engine's definition model (schema version "
             f"{workflow.SCHEMA_VERSION}). A workflow is data: the [Design tab](../docs/design-tab.md) edits it, "
             "validates it and publishes versions; an epic pins the version it runs. Machine-readable: "
             "[workflow.schema.json](workflow.schema.json)."]
    parts += _schema_tables(schema, "WorkflowDef")
    return "\n".join(parts) + "\n"


def workflow_schema_json() -> str:
    from edp8 import workflow
    return json.dumps(workflow.WorkflowDef.model_json_schema(by_alias=True), indent=2) + "\n"


# ----------------------------------------------------------------------------- models catalog


def models_md() -> str:
    from edp8 import model_catalog as mc
    parts = ["# Models catalog", "",
             "Generated at build from the models catalog's field table. The catalog (`models.json` in your data "
             "folder, edited in Admin → Models) lists every model a seat may run on and, per role, the models "
             "that role may use. Credentials never go in the catalog; they are secret settings.", "",
             "## Top-level keys", ""]
    parts.append(_table(["Key", "Meaning"], [[_code(k), _cell(v)] for k, v in mc.CATALOG_KEY_DOCS.items()]))
    parts += ["", "## A model row", "",
              "`models.<model id>` is one row; the id is what the harness is started with.", ""]
    parts.append(_table(["Field", "Meaning"], [[_code(k), _cell(v)] for k, v in mc.MODEL_FIELD_DOCS.items()]))
    parts += ["", "## Allowed values", "",
              "- `harness`: " + ", ".join(f"`{h}`" for h in sorted(mc.HARNESSES)),
              "- `effort_cap`: " + ", ".join(f"`{e}`" for e in sorted(mc.EFFORTS))
              + " (a `claude` row may not cap at `high`)",
              "- " + ", ".join(f"`{h}`" for h in sorted(mc.HARNESS_WINDOWS))
              + " rows may leave `context_window` and `auto_compact` unset: the harness reports its own.",
              "- `auto_compact` must be below `context_window`; both are positive integers (tokens)."]
    return "\n".join(parts) + "\n"


# ----------------------------------------------------------------------------- downloads


def load_release(fixture: str | None = None, timeout: float = 15.0) -> dict[str, Any] | None:
    """The latest release: a JSON fixture when given (HERONRY_SITE_RELEASE_JSON), else the GitHub Releases API.
    None when there is no release yet or GitHub is unreachable: the page then links the Releases page."""
    fixture = fixture if fixture is not None else os.environ.get("HERONRY_SITE_RELEASE_JSON")
    if fixture:  # `{repo_url}` in a fixture is this repo's URL, so a fixture never hardcodes the slug
        return json.loads(Path(fixture).read_text(encoding="utf-8").replace("{repo_url}", brand()["repo_url"]))
    import urllib.error
    import urllib.request
    req = urllib.request.Request(f"https://api.github.com/repos/{brand()['repo_slug']}/releases/latest",
                                 headers={"Accept": "application/vnd.github+json", "User-Agent": "heronry-site"})
    token = os.environ.get("GITHUB_TOKEN")
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:  # noqa: S310 — fixed https URL
            return json.loads(r.read().decode("utf-8"))
    except (urllib.error.URLError, OSError, ValueError):
        return None


#: the native installers the release ships (no AppImage: design §4.9):
#: key, OS name on the card, systems it runs on, file suffix, file type, the command-line script for that OS
INSTALLERS = (("windows", "Windows", "Windows 10/11", ".msi", "MSI installer", "install.ps1"),
              ("macos", "macOS", "Apple Silicon and Intel", ".dmg", "Disk image (DMG)", "install.sh"),
              ("linux", "Linux", "Ubuntu 24.04+ / Debian 13", ".deb", "Debian package (deb)", "install.sh"))


def _size(n: Any) -> str | None:
    """A release asset's `size` (bytes) as the button shows it, or None when the release does not say."""
    if not isinstance(n, int) or n <= 0:
        return None
    for unit, div in (("GB", 1 << 30), ("MB", 1 << 20), ("KB", 1 << 10)):
        if n >= div:
            return f"{n / div:.1f} {unit}"
    return f"{n} B"


def downloads(release: dict[str, Any] | None) -> dict[str, Any]:
    b = brand()
    rows = (release or {}).get("assets", [])
    assets = {a["name"]: a["browser_download_url"] for a in rows}
    sizes = {a["name"]: _size(a.get("size")) for a in rows}
    tag = (release or {}).get("tag_name")
    out: dict[str, Any] = {"tag": tag, "release_url": (release or {}).get("html_url") or b["releases_url"],
                           "installers": [], "sums": assets.get("SHA256SUMS"),
                           "attestations": f"{b['repo_url']}/attestations"}
    base = f"{b['releases_url']}/download" if not tag else f"{b['repo_url']}/releases/download/{tag}"
    out["ps1"] = assets.get("install.ps1") or f"{base}/install.ps1"
    out["sh"] = assets.get("install.sh") or f"{base}/install.sh"
    for key, os_name, runs_on, suffix, kind, script in INSTALLERS:
        name = next((n for n in sorted(assets) if n.lower().endswith(suffix)), None)
        out["installers"].append({"key": key, "os": os_name, "runs_on": runs_on, "kind": kind, "file": name,
                                  "size": sizes.get(name) if name else None,
                                  "url": assets[name] if name else b["releases_url"],
                                  "script": script, "script_url": out["ps1" if script.endswith(".ps1") else "sh"]})
    return out


def _esc(text: Any) -> str:
    return html.escape(str(text), quote=True)


def _download_card(i: dict[str, Any], d: dict[str, Any]) -> str:
    """One OS: a single primary button (OS, file type, size), the file name, and the quiet secondary links."""
    meta = " · ".join(x for x in (i["kind"], i["size"]) if x) if i["file"] else "on the releases page"
    quiet = [f'<a href="{_esc(i["script_url"])}">{_esc(i["script"])}</a> (command line)']
    if d["sums"]:
        quiet.append(f'<a href="{_esc(d["sums"])}">SHA256SUMS</a>')
    quiet.append(f'<a href="{_esc(d["attestations"])}">attestation</a>')
    file = (f'<p class="hy-dl-file" title="{_esc(i["file"])}">{_esc(i["file"])}</p>' if i["file"] else "")
    return (f'<div class="hy-dl-card" data-os="{i["key"]}">'
            f'<p class="hy-dl-head"><span class="hy-dl-os">{_esc(i["os"])}</span>'
            f'<span class="hy-dl-runs">{_esc(i["runs_on"])}</span></p>'
            f'<a class="md-button md-button--primary hy-dl" data-os="{i["key"]}" href="{_esc(i["url"])}">'
            f'<span class="hy-dl-label">Download for {_esc(i["os"])}</span>'
            f'<span class="hy-dl-meta">{_esc(meta)}</span></a>'
            f'{file}<p class="hy-dl-more">{" · ".join(quiet)}</p></div>')


def downloads_md(release: dict[str, Any] | None) -> str:
    d = downloads(release)
    b = brand()
    lines = []
    if d["tag"]:
        lines += [f"Latest release: **[{d['tag']}]({d['release_url']})**.", ""]
    else:
        lines += [f"No release is published yet; the buttons open the [releases page]({d['release_url']}).", ""]
    # one raw-HTML block (no blank line inside, so Markdown leaves it whole)
    lines.append('<div class="hy-downloads">' + "".join(_download_card(i, d) for i in d["installers"]) + "</div>")
    lines += ["", f'<p class="hy-dl-all">Python wheels, sdists, the VS Code extension and every other file: '
                  f'<a href="{_esc(d["release_url"])}">all release files</a>.</p>']
    lines += ["", "### Command line", "",
              "Windows (PowerShell):", "", "```powershell", f"irm {d['ps1']} | iex", "```", "",
              "macOS and Linux:", "", "```sh", f"curl -LsSf {d['sh']} | sh", "```", "",
              f"Then open a new terminal and run `{b['cli_name']} init`, then `{b['cli_name']} start`."]
    if d["sums"]:
        lines += ["", f"Checksums: [SHA256SUMS]({d['sums']})."]
    return "\n".join(lines) + "\n"
