"""Small, failure-tolerant persistence layer for human UI avatars."""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path

_VALID_AVATARS = {f"human-{number:02d}" for number in range(1, 9)}


def avatar_preferences_path() -> Path:
    """Return the per-install avatar preference file."""
    home = Path(os.environ.get("EDP8_HOME", str(Path(__file__).resolve().parents[2])))
    return home / "ui-avatars.json"


def load_avatar_preferences(path: str | Path | None = None) -> dict[str, str]:
    """Load valid preferences; an absent or damaged file behaves like an empty one."""
    target = Path(path) if path is not None else avatar_preferences_path()
    try:
        value = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        return {}
    if not isinstance(value, dict):
        return {}
    return {str(key): avatar for key, avatar in value.items()
            if isinstance(avatar, str) and avatar in _VALID_AVATARS}


def save_avatar_preference(participant_id: str, avatar_id: str,
                           path: str | Path | None = None) -> None:
    """Atomically save one validated preference without risking a partial JSON file."""
    if avatar_id not in _VALID_AVATARS:
        raise ValueError(f"unknown avatar: {avatar_id}")
    target = Path(path) if path is not None else avatar_preferences_path()
    target.parent.mkdir(parents=True, exist_ok=True)
    preferences = load_avatar_preferences(target)
    preferences[str(participant_id)] = avatar_id
    temporary: Path | None = None
    try:
        with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=target.parent,
                                         prefix=f".{target.name}.", suffix=".tmp",
                                         delete=False) as stream:
            json.dump(preferences, stream, indent=2, sort_keys=True)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
            temporary = Path(stream.name)
        temporary.replace(target)
    finally:
        if temporary is not None and temporary.exists():
            try:
                temporary.unlink()
            except OSError:
                pass
