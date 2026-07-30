r"""Captured tools-demo for design-templates-mcp (no shell-command gate, Windows host).

Exercises BOTH server tools end-to-end by importing the catalog module the
FastMCP shims delegate to (so this proves the exact code path the MCP boundary
runs), against the REAL ``eda-designs`` content root, and captures the combined
JSON to ``design-templates-mcp/samples/tools-demo.json``.

Cases captured (matches the b1 acceptance):
  1. list_templates()                       — full catalog, all 4 kinds
  2. list_templates(kind="theme")           — filtered listing
  3. fetch_template_by_name("theme","default")    — real token JSON + variables.css text
  4. fetch_template_by_name("component","Button") — real tsx + css text
  5. fetch_template_by_name("doc", <first doc>)   — real markdown text
  6. fetch_template_by_name("theme","__does_not_exist__") — INTENTIONAL error:
     a structured ok=false envelope listing valid names, NOT a traceback.

Run:  python scripts/tools_demo.py
Behavior is proven by inspecting the captured file on disk — no kind="command"
acceptance gate is used (Windows-host plan constraint).
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT / "src"))

from design_templates_mcp import catalog  # noqa: E402


def _first_doc_name() -> str:
    """Pick a doc name live from the catalog so the demo never hardcodes one."""
    docs = catalog.list_templates(kind="doc").get("templates", [])
    return docs[0]["name"] if docs else "readme"


def main() -> int:
    doc_name = _first_doc_name()

    full = catalog.list_templates()
    themes = catalog.list_templates(kind="theme")
    theme_default = catalog.fetch_template_by_name("theme", "default")
    component_button = catalog.fetch_template_by_name("component", "Button")
    doc_fetch = catalog.fetch_template_by_name("doc", doc_name)
    unknown = catalog.fetch_template_by_name("theme", "__does_not_exist__")

    out = {
        "designs_root": str(catalog.designs_root()),
        "cases": {
            "list_templates()": full,
            'list_templates(kind="theme")': themes,
            'fetch_template_by_name("theme","default")': theme_default,
            'fetch_template_by_name("component","Button")': component_button,
            f'fetch_template_by_name("doc","{doc_name}")': doc_fetch,
            'fetch_template_by_name("theme","__does_not_exist__")': unknown,
        },
    }

    samples = _ROOT / "samples"
    samples.mkdir(exist_ok=True)
    target = samples / "tools-demo.json"
    target.write_text(json.dumps(out, indent=2), encoding="utf-8")

    # Operator-facing summary (scripts/ may print — see pyproject ruff ignore).
    print(f"wrote {target}")
    print(f"  full catalog count:     {full.get('count')}")
    print(f"  theme-filtered count:   {themes.get('count')}")
    print(f"  theme/default ok:       {theme_default.get('ok')} "
          f"({len(theme_default.get('contents', []))} files)")
    print(f"  component/Button ok:    {component_button.get('ok')} "
          f"({len(component_button.get('contents', []))} files)")
    print(f"  doc/{doc_name} ok:      {doc_fetch.get('ok')}")
    print(f"  unknown-name ok:        {unknown.get('ok')} "
          f"(expected False; error={unknown.get('error')!r})")

    # Hard assertions so a regression fails loudly rather than capturing junk.
    assert full.get("ok") and full.get("count", 0) >= 4, "full catalog broken"
    assert themes.get("ok"), "theme-filtered listing broken"
    assert theme_default.get("ok") and theme_default.get("contents"), "theme fetch broken"
    assert component_button.get("ok") and component_button.get("contents"), "component fetch broken"
    assert doc_fetch.get("ok") and doc_fetch.get("contents"), "doc fetch broken"
    assert unknown.get("ok") is False and "available" in unknown, (
        "unknown-name case must return a structured ok=false envelope, not raise"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
