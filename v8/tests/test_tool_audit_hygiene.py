"""S23-T6 reopen (qa m-866f9f2d26): scripts/tool_audit.py records no host-user path and caps context() at the
registry's board.context_budget_b default, not a literal."""
from __future__ import annotations

import importlib.util
import json
import tempfile
from pathlib import Path

from edp8 import settings

ROOT = Path(__file__).resolve().parents[1]


def _audit():
    spec = importlib.util.spec_from_file_location("tool_audit_under_test", ROOT / "scripts" / "tool_audit.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_redact_replaces_temp_and_home_in_every_spelling():
    audit = _audit()
    temp, home = tempfile.gettempdir(), str(Path.home())
    row = {"note": f"not_found under {temp}\\edp-tool-audit-x\\transcripts",
           "args": {"path": f"{home}/Documents/a.png"},
           "hits": [repr(Path(temp) / "y"), temp.replace("\\", "/").upper() + "/z"]}
    out = json.dumps(audit.redact(row))
    user = Path.home().name
    assert user.lower() not in out.lower()
    assert "<TEMP>" in out and "<HOME>" in out


def test_context_cap_follows_the_registry_default():
    audit = _audit()
    budget = int(settings.setting("EDP8_CONTEXT_BUDGET_B").default)
    assert audit.CALL_CAP_B["context"] == max(audit.PAGE_CAP_B, budget)
    assert "context_delta" not in audit.CALL_CAP_B  # every other tool keeps the 8 KB page cap
