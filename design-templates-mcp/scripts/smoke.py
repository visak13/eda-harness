r"""Smoke test for design-templates-mcp (no shell-command gate, Windows host).

Imports the server's tool functions directly (via the catalog module, which
the FastMCP shims delegate to), calls list_templates() then
fetch_template_by_name("theme", "default") against the REAL eda-designs root,
and captures the combined JSON result to
``design-templates-mcp/samples/smoke-output.json``.

Run:  python scripts/smoke.py
This proves end-to-end behavior by inspecting the captured file on disk —
no kind="command" acceptance gate is used.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT / "src"))

from design_templates_mcp import catalog  # noqa: E402


def main() -> int:
    listing = catalog.list_templates()
    fetched = catalog.fetch_template_by_name("theme", "default")

    out = {
        "designs_root": str(catalog.designs_root()),
        "list_templates": listing,
        "fetch_template_by_name(theme/default)": fetched,
    }

    samples = _ROOT / "samples"
    samples.mkdir(exist_ok=True)
    target = samples / "smoke-output.json"
    target.write_text(json.dumps(out, indent=2), encoding="utf-8")

    names = [t["name"] for t in listing.get("templates", []) if t["kind"] == "theme"]
    print(f"wrote {target}")
    print(f"  catalog count: {listing.get('count')}")
    print(f"  themes: {names}")
    print(f"  fetch theme/default ok: {fetched.get('ok')}, files: {fetched.get('files')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
