"""t-bdd34121ee (epic criterion c-8093e35929): no shipped source derives the repo layout from `__file__`.

A `Path(__file__).parents[N]` (or a `.parent.parent` climb) only finds the checkout when the code runs from
it; an installed wheel has no v8/ above it. Dev-checkout lookups go through the settings registry
(materialise.checkout_root / source_root). The scan covers every package the release builds, with no allowlist.
"""
from __future__ import annotations

import ast
import re
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]  # tests are not shipped
WORKFLOW = REPO / ".github" / "workflows" / "installers.yml"


def _shipped_projects() -> list[str]:
    """The projects the release builds wheels from (installers.yml `for p in ...; do uv build`)."""
    m = re.search(r"for p in ([\w\- ]+); do uv build --wheel", WORKFLOW.read_text(encoding="utf-8"))
    assert m, f"{WORKFLOW} no longer names the wheel projects: update this guard"
    return m.group(1).split()


def _rooted(node: ast.AST, tainted: set[str]) -> bool:
    """True when the path expression is built from `__file__` (directly, via Path()/resolve(), or a name)."""
    while True:
        if isinstance(node, ast.Name):
            return node.id == "__file__" or node.id in tainted
        if isinstance(node, (ast.Attribute, ast.Subscript)):
            node = node.value
        elif isinstance(node, ast.Call):  # Path(__file__), os.path.abspath(__file__), <path>.resolve()
            if any(_rooted(a, tainted) for a in node.args):
                return True
            if not isinstance(node.func, ast.Attribute):
                return False
            node = node.func.value
        elif isinstance(node, ast.BinOp):
            node = node.left
        else:
            return False


def offences(source: str, name: str = "<src>") -> list[str]:
    tree = ast.parse(source, name)
    tainted: set[str] = set()
    for n in ast.walk(tree):
        if isinstance(n, ast.Assign) and _rooted(n.value, set()):
            tainted.update(t.id for t in n.targets if isinstance(t, ast.Name))
    out = []
    for n in ast.walk(tree):
        hit = None
        if isinstance(n, ast.Attribute) and n.attr == "parents" and _rooted(n.value, tainted):
            hit = "parents[N]"
        elif (isinstance(n, ast.Attribute) and n.attr == "parent" and isinstance(n.value, ast.Attribute)
              and n.value.attr == "parent" and _rooted(n.value.value, tainted)):
            hit = ".parent.parent"
        if hit:
            out.append(f"{name}:{n.lineno}: {hit} on a __file__ path")
    return sorted(set(out))


def test_the_detector_catches_every_shape():
    for bad in ("from pathlib import Path\nr = Path(__file__).resolve().parents[2]\n",
                "import os\nfrom pathlib import Path\nr = Path(os.path.abspath(__file__)).parents[1] / 'x'\n",
                "from pathlib import Path\nr = Path(__file__).resolve().parent.parent.parent\n",
                "from pathlib import Path\nhere = Path(__file__).resolve()\nroot = here.parents[3]\n"):
        assert offences(bad), bad
    for ok in ("from pathlib import Path\nd = Path(__file__).resolve().parent / 'dist'\n",
               "from pathlib import Path\nh = Path(__file__).read_bytes()\n",
               "from pathlib import Path\ndef f(p: Path):\n    return p.parent.parent\n"):
        assert not offences(ok), ok


def test_no_shipped_package_derives_the_repo_layout_from_file():
    projects = _shipped_projects()
    assert {"v8", "edp-contracts", "edp-pool", "edp-broker"} <= set(projects), projects
    scanned, found = 0, []
    for proj in projects:
        src = REPO / proj / "src"
        assert src.is_dir(), src
        for f in sorted(src.rglob("*.py")):
            scanned += 1
            found += offences(f.read_text(encoding="utf-8"), str(f.relative_to(REPO)))
    assert scanned > 100, scanned  # the scan really walked the shipped trees
    assert found == [], "\n".join(found)
