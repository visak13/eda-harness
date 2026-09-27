"""Read-only comparison of the audit's Claude-only roots with a Codex mirror root.
Writes only a summary; never prints transcript content or credentials.
"""
import json
from pathlib import Path
import sys
ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "src"))
from edp8.harvest_cost import find_log, compute
pid = "adversary.t-91393f0b57"
audit_root = ROOT.parent / "edp-pool" / ".claude-pool" / "projects"
bad = find_log(pid, claude_roots=(audit_root,), codex_roots=(audit_root,))
good = find_log(pid, claude_roots=(), codex_roots=(ROOT.parent / ".logs",))
assert bad is None and good is not None
result = compute(pid, since="2026-09-27T05:41:04Z", log=good[1])
summary = {"audit_roots_found": False, "codex_root_found": True, "kind": good[0],
           "log_name": good[1].name, "compute_succeeded": True, "tokens": result["tokens"]}
Path(__file__).with_name("harvest-results.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
print(json.dumps(summary))
