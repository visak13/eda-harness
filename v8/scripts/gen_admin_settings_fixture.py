"""Regenerate web/src/test/fixtures/admin-settings.json from the live registry (GET /v1/admin/settings shape).

Runs in a clean environment (no EDP_*/HERONRY_* vars, a throwaway home) so every row shows its default and
nothing machine-specific leaks in; config_file is the "<path>" placeholder. Usage:
    .venv/Scripts/python.exe scripts/gen_admin_settings_fixture.py
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

OUT = Path(__file__).resolve().parents[1] / "web" / "src" / "test" / "fixtures" / "admin-settings.json"
CHILD = """
import json, sys
from edp8.admin import settings_api
view = settings_api.listing()
view["config_file"] = "<path>"
json.dump(view, sys.stdout, indent=1, ensure_ascii=False)
"""


def main() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        env = {k: v for k, v in os.environ.items() if not k.startswith(("EDP", "HERONRY", "CODE_GUARD"))}
        env["EDP_HOME"] = tmp
        out = subprocess.run([sys.executable, "-c", CHILD], env=env, capture_output=True, text=True,
                             encoding="utf-8", check=True).stdout
    out = out.replace(tmp.replace("\\", "\\\\"), "<home>")
    OUT.write_text(out + "\n", encoding="utf-8")
    print(f"wrote {OUT} ({len(json.loads(out)['groups'])} groups)")


if __name__ == "__main__":
    main()
