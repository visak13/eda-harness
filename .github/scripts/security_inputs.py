"""Writes <out>/<package>.in: the third-party runtime dependencies of edp-contracts, edp-pool and edp-broker
(their edp-* siblings are path packages, not on PyPI), for `uv pip compile` then `pip-audit` in ci.yml's security job.
v8 is audited from its uv.lock instead (`uv export`)."""
import re
import sys
import tomllib
from pathlib import Path

out = Path(sys.argv[1])
out.mkdir(parents=True, exist_ok=True)
for pkg in ("edp-contracts", "edp-pool", "edp-broker"):
    deps = tomllib.loads(Path(pkg, "pyproject.toml").read_text(encoding="utf-8"))["project"].get("dependencies", [])
    keep = [d for d in deps if not re.match(r"edp[-_]", d.strip(), re.I)]
    (out / f"{pkg}.in").write_text("".join(d + "\n" for d in keep), encoding="utf-8")
    print(f"{pkg}: {len(keep)} third-party dependencies")
