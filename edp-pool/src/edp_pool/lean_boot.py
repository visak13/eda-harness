"""Lean boot for a Claude seat (S8): what a seat's first call carries that no seat uses, taken off.

Four independent savings, each measured on a private seat (v8/docs/evidence/e0cec-s8/after):
  * claude.ai connectors (and their MCP instructions): `ENABLE_CLAUDEAI_MCP_SERVERS=false`;
  * the skill listing trimmed to the role's own skills (bundled + marketplace skills off, other roles' cards
    user-invocable-only) via a per-card `--settings` file;
  * tools no seat calls denied (`permissions.deny`), `Workflow` included: its description is 5.5k chars and
    balloons to 22.9k once bundled skills are off, so the trim only pays with it denied;
  * output caps (Bash / Read) so one runaway result cannot sit in context for the rest of the session.

`EDP_LEAN_BOOT=0` switches the first three off (the caps stay); every env value is a setdefault, so a value the
operator exports for the pool wins. Claude seats only: Pi/Codex seats never see these knobs.
"""

from __future__ import annotations

import functools
import json
import re
from pathlib import Path

from edp_contracts import settings

#: first-call savings (EDP_LEAN_BOOT=0 turns these off)
LEAN_ENV = {"ENABLE_CLAUDEAI_MCP_SERVERS": "false", "CLAUDE_CODE_DISABLE_CRON": "1"}
#: output caps: Bash chars (claude default 30000) and one Read in tokens (claude default 25000)
CAP_ENV = {"BASH_MAX_OUTPUT_LENGTH": "15000", "CLAUDE_CODE_FILE_READ_MAX_OUTPUT_TOKENS": "8000"}

#: tools no seat calls (cards, guides and bundles never name them; the heartbeat is the feed driver's now)
DENY_TOOLS = ["Workflow", "CronCreate", "CronDelete", "CronList", "EnterWorktree", "ExitWorktree", "DesignSync",
              "RemoteTrigger", "PushNotification", "NotebookEdit", "EndConversation", "ArtifactComments",
              "ArtifactData"]

#: skills claude lists that no role card names: marketplace skills plus the pool-config ones the template
#: already turns off. A name that does not exist is ignored by claude, so a stale entry is harmless.
OFF_SKILLS = [
    "anthropic-skills:built-in-browser", "anthropic-skills:chrome-browser", "anthropic-skills:computer-use",
    "anthropic-skills:deep-research", "anthropic-skills:docs", "anthropic-skills:docx",
    "anthropic-skills:google-workspace", "anthropic-skills:import-memory", "anthropic-skills:morning",
    "anthropic-skills:pdf", "anthropic-skills:pptx", "anthropic-skills:skill-creator", "anthropic-skills:xlsx",
    "artifact-design", "artifact-capabilities", "artifact-diagramming", "claude-in-chrome",
]

_CARD_RE = re.compile(r"^[a-z][a-z0-9-]*$")
_SLASH_RE = re.compile(r"(?<![\w/])/([a-z][a-z0-9-]*)")


def enabled() -> bool:
    return bool(settings.get("EDP_LEAN_BOOT"))


def apply_env(env: dict) -> dict:
    """setdefault the caps (always) and the lean-boot env (unless EDP_LEAN_BOOT=0) onto a seat's env."""
    for k, v in CAP_ENV.items():
        env.setdefault(k, v)
    if enabled():
        for k, v in LEAN_ENV.items():
            env.setdefault(k, v)
    return env


@functools.lru_cache(maxsize=1)
def can_run_listener() -> bool:
    """True when this pool's interpreter can run `-m edp8.feed_driver` (the installed heronry.exe can; a dev pool
    whose venv lacks edp8 cannot). Checked once per pool process; a seat that cannot run the listener keeps the
    Monitor wake instead of getting a mod that would respawn a failing child forever."""
    import subprocess
    import sys

    try:
        return subprocess.run([sys.executable, "-c", "import edp8.feed_driver"], capture_output=True,
                              timeout=60).returncode == 0
    except (OSError, subprocess.SubprocessError):
        return False


def apply_wake_mod(env: dict, agent_home: str | Path | None) -> dict:
    """Point a Claude seat at the edp-wake mod (e0cec s-e60c3d42ad): `CLAUDE_CODE_PLUGIN_DIRS` loads the folder of
    mods under `<agent home>/.claude/mods`, and `EDP8_FEED_PY` is the interpreter that runs the feed listener the
    mod starts (the pool and the board's MCP proxy are the same install). setdefault, so an operator value wins;
    `EDP_WAKE_MOD=0` leaves the seat on the Monitor wake. Nothing is set when the agent home ships no mod or this
    interpreter cannot run the listener."""
    import os
    import sys

    # the switch is read from the seat's effective env (the caller's extra_env is already merged into `env`),
    # then the pool's own; an operator's other CLAUDE_CODE_PLUGIN_DIRS entries are never touched
    if env.get("EDP_WAKE_MOD", os.environ.get("EDP_WAKE_MOD", "1")) == "0" or agent_home is None:
        return env
    mods = Path(agent_home) / ".claude" / "mods"
    if (mods / "edp-wake" / ".claude-plugin" / "plugin.json").is_file() and can_run_listener():
        env.setdefault("CLAUDE_CODE_PLUGIN_DIRS", str(mods))
        env.setdefault("EDP8_FEED_PY", sys.executable)
    return env


def _dirs(home: Path) -> tuple[Path, Path]:
    return home / ".claude" / "skills", home / ".claude" / "commands"


def role_skills(card: str, agent_home: str | Path) -> tuple[set[str], set[str]]:
    """(skills the card names, every skill/card name the agent home defines). A card names a skill by
    `/name` in its text; the card itself is always kept."""
    skills_dir, cmds_dir = _dirs(Path(agent_home))
    skills = {p.name for p in skills_dir.iterdir() if p.is_dir()} if skills_dir.is_dir() else set()
    cards = {p.stem for p in cmds_dir.glob("*.md")} if cmds_dir.is_dir() else set()
    try:
        text = (cmds_dir / f"{card}.md").read_text(encoding="utf-8")
    except OSError:
        text = ""
    named = {m for m in _SLASH_RE.findall(text) if m in skills}
    return named, skills | cards


def settings_dict(card: str, agent_home: str | Path) -> dict:
    """The per-card settings overlay: role skills only on the listing, unused tools denied, connectors off."""
    named, known = role_skills(card, agent_home)
    keep = named | {card}
    overrides = {n: "off" for n in OFF_SKILLS}
    cmds = Path(agent_home) / ".claude" / "commands"
    for n in known - keep:
        # another role's card stays reachable to a human (`/qa`) but is not advertised to the model
        overrides[n] = "user-invocable-only" if (cmds / f"{n}.md").is_file() else "off"
    return {"disableClaudeAiConnectors": True, "disableBundledSkills": True, "skillOverrides": overrides,
            "permissions": {"deny": list(DENY_TOOLS)}}


def settings_path(config_dir: str | Path, card: str, agent_home: str | Path) -> Path | None:
    """Write `<config>/lean/<card>.settings.json` (rewritten only when its content changed); None on failure
    — a seat must always boot, lean or not."""
    if not _CARD_RE.match(card or ""):
        return None
    body = json.dumps(settings_dict(card, agent_home), indent=1, sort_keys=True)
    try:
        d = Path(config_dir) / "lean"
        d.mkdir(parents=True, exist_ok=True)
        p = d / f"{card}.settings.json"
        if not p.is_file() or p.read_text(encoding="utf-8") != body:
            p.write_text(body, encoding="utf-8")
        return p
    except OSError:
        return None


def lean_args(role: str, extra_env: dict | None, agent_home: str | Path | None, config_dir: str | Path) -> list[str]:
    """`--settings <file>` for the seat's card, or [] (lean boot off, no agent home, or the file unwritable)."""
    if not enabled() or not agent_home or not (Path(agent_home) / ".claude" / "commands").is_dir():
        return []
    card = str((extra_env or {}).get("EDP_CARD") or role or "")
    p = settings_path(config_dir, card, agent_home)
    return ["--settings", str(p)] if p else []
