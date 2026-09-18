"""Dependency-free inline SVG identities used by the board UI."""

from __future__ import annotations

import hashlib
import html
from typing import Any, Mapping

from .avatar_templates import BOT_TEMPLATES

HUMAN_AVATAR_IDS = tuple(f"human-{number:02d}" for number in range(1, 9))
_HUMAN_NAMES = ("Rowan", "Mira", "Dev", "June", "Sam", "Noor", "Eli", "Aya")
_HUMAN_COLORS = (
    ("#F3B89A", "#8B4A32", "#168B82"), ("#8B5CF6", "#24212B", "#EABF3B"),
    ("#4F8EDC", "#54362E", "#D95C5C"), ("#8DD9B5", "#D8D7DA", "#5865F2"),
    ("#D98C9D", "#17191E", "#2E9C64"), ("#D9A441", "#633A68", "#7C3AED"),
    ("#E79052", "#25272C", "#168AAD"), ("#70BCE8", "#4B252B", "#C84455"),
)


def _svg(body: str, label: str, size: int, decorative: bool = False) -> str:
    accessibility = "aria-hidden='true'" if decorative else f"role='img' aria-label='{html.escape(label, quote=True)}'"
    return (f"<svg class='avatar-svg' {accessibility} width='{int(size)}' height='{int(size)}' "
            f"viewBox='0 0 36 36' xmlns='http://www.w3.org/2000/svg'>{body}</svg>")


def system_avatar_svg(size: int = 36, *, unknown: bool = False) -> str:
    template = BOT_TEMPLATES["unknown" if unknown else "system"]
    return _svg(template["body"], template["label"], size)


def human_avatar_svg(avatar_id: str, size: int = 36) -> str:
    try:
        index = HUMAN_AVATAR_IDS.index(avatar_id)
    except ValueError:
        index = 0
    background, hair, shirt = _HUMAN_COLORS[index]
    hair_shapes = (
        "M10 17V13c1-8 14-9 17-3-6-1-8 5-17 7", "M9 18V12c2-8 17-8 18 1v7l-4-6-10 1-4 3",
        "M10 14c1-7 4-8 6-5 2-4 5-2 5 1 3-3 6 0 5 5", "M10 15c2-8 13-9 17-2l-6-2-4 4-7 2",
        "M9 16c2-9 8-10 10-5 4-5 9-1 8 5l-6-3-3 3-4-2-5 4", "M9 18c0-10 18-13 19 0l-4 3-12-1-3-2",
        "M9 15c2-7 5-8 8-7l2 4 8-2v6l-4-2-4 3-5-3-5 3", "M11 15c-5-4-1-10 4-7 2-5 6-3 6 1 7-2 9 5 4 8",
    )[index]
    extra = ""
    if index == 5:
        extra = f"<path d='M9 18Q18 5 28 18v8H9z' fill='{hair}'/><path d='M13 18h10v9H13z' fill='#D9A07D'/>"
    elif index == 7:
        extra = f"<circle cx='11' cy='9' r='4' fill='{hair}'/><circle cx='25' cy='9' r='4' fill='{hair}'/>"
    body = (f"<rect width='36' height='36' rx='8' fill='{background}'/><path d='M4 36c1-9 7-13 14-13s13 4 14 13' fill='{shirt}'/>"
            f"<path d='M11 14c0-9 14-9 14 0v5c0 6-4 8-7 8s-7-2-7-8z' fill='#D9A07D'/><path d='{hair_shapes}' fill='{hair}'/>"
            f"{extra}<circle cx='15' cy='18' r='1' fill='#3A2B29'/><circle cx='22' cy='18' r='1' fill='#3A2B29'/>"
            "<path d='M16 22q2 2 4 0' fill='none' stroke='#7D4B42' stroke-width='1.2' stroke-linecap='round'/>")
    return _svg(body, f"Avatar {_HUMAN_NAMES[index]}", size)


def role_avatar_svg(role: Any, model: str | None = None, size: int = 36) -> str:
    role_value = getattr(role, "value", role)
    role_name = str(role_value or "system").lower()
    if role_name == "consultant" or (model and "gpt" in model.lower()):
        role_name = "consultant"
    template = BOT_TEMPLATES.get(role_name, BOT_TEMPLATES["unknown"])
    return _svg(template["body"], template["label"], size)


def avatar_id_for(participant: Any, preferences: Mapping[str, str]) -> str:
    if participant is None or getattr(participant, "type", None) != "human":
        return "system"
    selected = preferences.get(str(participant.id))
    if selected in HUMAN_AVATAR_IDS:
        return selected
    digest = hashlib.sha256(str(participant.id).encode("utf-8")).digest()
    return HUMAN_AVATAR_IDS[int.from_bytes(digest[:2], "big") % len(HUMAN_AVATAR_IDS)]


def avatar_svg(participant: Any, size: int = 36, decorative: bool = False) -> str:
    if participant is None:
        return system_avatar_svg(size, unknown=True)
    if getattr(participant, "type", None) == "human":
        avatar_id = getattr(participant, "avatar_id", None) or "human-01"
        result = human_avatar_svg(avatar_id, size)
    else:
        result = role_avatar_svg(getattr(participant, "role", None), getattr(participant, "model", None), size)
    return result.replace("role='img' aria-label=", "aria-hidden='true' data-label=") if decorative else result


def avatar_picker_html(participant: Any, selected_id: str, hidden_fields: str) -> str:
    tiles = "".join(
        f"<label class='avatar-choice'><input type='radio' name='avatar' value='{avatar_id}'"
        f"{' checked' if avatar_id == selected_id else ''}><span>{human_avatar_svg(avatar_id, 48)}"
        f"<small>{_HUMAN_NAMES[index]}</small></span></label>"
        for index, avatar_id in enumerate(HUMAN_AVATAR_IDS)
    )
    return ("<details class='avatar-picker'><summary>Change avatar</summary>"
            f"<form method='post' action='/ui/me/avatar'>{hidden_fields}<div class='avatar-grid'>{tiles}</div>"
            "<button type='submit'>Save avatar</button></form></details>")
