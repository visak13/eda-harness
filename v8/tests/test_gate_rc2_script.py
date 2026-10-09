"""The RC2 upgrade gate launches nothing the host antivirus quarantines (shared-host-rules a781bf99, architect
m-06f2ca468b): no -ExecutionPolicy Bypass, no WMI Win32_Process Create, no hidden or detached launch.
"""
import re
from pathlib import Path

GATE = Path(__file__).resolve().parents[1] / "scripts" / "gate_rc2_upgrade.ps1"


def test_gate_launches_powershell_without_bypass():
    launches = [l for l in GATE.read_text(encoding="utf-8").splitlines() if re.search(r"\bpowershell\b.*-File\b", l)]
    assert launches, "the gate's build step and its usage line launch powershell -File"
    assert [l for l in launches if re.search(r"-ExecutionPolicy\s+Bypass", l, re.I)] == []


def test_gate_never_launches_hidden_or_detached():
    text = GATE.read_text(encoding="utf-8")
    assert not re.search(r"Win32_Process\s*-MethodName\s*Create|Invoke-CimMethod|WindowStyle\s+Hidden", text, re.I)
    assert "Launch it detached" not in text


def test_msi_memory_floor_is_a_parameter_defaulting_to_800_mb():
    """m-8a9d37e021 (owner m-d135dff5c4): the hard-coded 2560 MB floor held a build that needs ~0.35 GB."""
    text = GATE.read_text(encoding="utf-8")
    assert re.search(r"\[int\]\$MinFreeMB\s*=\s*800\b", text)
    assert "2560" not in text
    pause = [l for l in text.splitlines() if "paused:" in l or "MB free for the" in l]
    assert len(pause) == 2 and all("$MinFreeMB" in l for l in pause), pause


# architect m-b7abaedb27 (adversary m-fcbc23ab01): after hop2's update no card or skill names a tool the product dropped
def _agent_home_scanner():
    import importlib.util
    spec = importlib.util.spec_from_file_location("gate_agent_home", GATE.with_name("gate_agent_home.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_agent_home_scan_names_stale_tools_and_kept_files(tmp_path):
    scan = _agent_home_scanner().scan
    (tmp_path / "commands").mkdir()
    (tmp_path / "skills" / "harvest").mkdir(parents=True)
    (tmp_path / "commands" / "engineer.md").write_text("`context()` then `assemble_ruleset(ticket_id=<story>)`; a `doc_type` field\n")
    (tmp_path / "skills" / "harvest" / "SKILL.md").write_text("the ruleset tool (assemble_ruleset) lists the docs\n")
    (tmp_path / "commands" / "qa.md.new").write_text("`context_delta(cursor=...)`\n")
    found = scan(tmp_path, {"context", "context_delta"}, {"assemble_ruleset"})
    assert found["unknown"] == {"assemble_ruleset": ["commands/engineer.md"]}
    assert found["removed"] == {"assemble_ruleset": ["commands/engineer.md", "skills/harvest/SKILL.md"]}
    assert found["new_files"] == ["commands/qa.md.new"]
    clean = tmp_path / "clean"
    (clean / "commands").mkdir(parents=True)
    (clean / "commands" / "engineer.md").write_text("`context()` then `context_delta(cursor=...)`; os.path.join(a) is code\n")
    assert scan(clean, {"context", "context_delta"}, {"assemble_ruleset"}) == {"unknown": {}, "removed": {}, "new_files": []}


def test_shipped_cards_and_skills_name_only_registered_tools():
    from edp8 import browser_proxy
    from edp8.bundles import ALL_TOOLS
    found = _agent_home_scanner().scan(GATE.parents[1] / ".claude", set(ALL_TOOLS) | set(browser_proxy.TOOL_NAMES))
    assert found == {"unknown": {}, "removed": {}, "new_files": []}


def test_hop2_reads_the_registry_before_and_after_the_update_and_checks_the_agent_home():
    text = GATE.read_text(encoding="utf-8")
    hop2 = text.split('if ($Phase -eq "hop2") {', 1)[1].split("\n}", 1)[0]
    before, update, after = (hop2.index(s) for s in (r'ToolRegistry "$Ev\hop2-tools-0.10.0.json"', 'Hx "hop2-update"',
                                                      r'ToolRegistry "$Ev\hop2-tools-0.10.1.json"'))
    assert before < update < after < hop2.index('Checks $H "hop2"')
    code = re.search(r'\$ToolsCode = ((?:"[^"]*"\s*\+?\s*)+)', text).group(1)
    assert "ALL_TOOLS" in code and "TOOL_NAMES" in code  # one string literal per line, no inner double quote
    checks = GATE.with_name("gate_rc2_checks.py").read_text(encoding="utf-8")
    assert 'HOME / "agent-home" / ".claude"' in checks and "hop2-tools-0.10.1.json" in checks


def test_stop_private_spares_the_shells_that_launched_the_gate():
    """hop2 never started after hop1 (run-hops-73aef932.bat, run-gate-63e1a4bb.bat): the owner's .bat names the gate
    folder on its command line, so hop1's opening StopPrivate stopped the bat's cmd.exe ("private pids stopped: 1")."""
    text = GATE.read_text(encoding="utf-8")
    callers = text.split("function Callers {", 1)[1].split("\n}", 1)[0]
    assert "ParentProcessId" in callers and "$PID" in callers
    stop = text.split("function StopPrivate {", 1)[1].split("\n}", 1)[0]
    assert "$callers = @(Callers)" in stop
    assert re.search(r"Where-Object \{ \$callers -notcontains \[int\]\$_\.ProcessId -and \(Under \$_ \$Gate\)", stop)
