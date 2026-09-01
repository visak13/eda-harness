"""Dependency-free inline SVG identities used by the board UI."""

from __future__ import annotations

import hashlib
import html
from typing import Any, Mapping

HUMAN_AVATAR_IDS = tuple(f"human-{number:02d}" for number in range(1, 9))
_HUMAN_NAMES = ("Rowan", "Mira", "Dev", "June", "Sam", "Noor", "Eli", "Aya")
_HUMAN_COLORS = (
    ("#F3B89A", "#8B4A32", "#168B82"), ("#8B5CF6", "#24212B", "#EABF3B"),
    ("#4F8EDC", "#54362E", "#D95C5C"), ("#8DD9B5", "#D8D7DA", "#5865F2"),
    ("#D98C9D", "#17191E", "#2E9C64"), ("#D9A441", "#633A68", "#7C3AED"),
    ("#E79052", "#25272C", "#168AAD"), ("#70BCE8", "#4B252B", "#C84455"),
)
_ROLE_COLORS = {"architect": "#5865F2", "engineer": "#168B68", "reviewer": "#8B5CF6",
                "adversary": "#D95C5C", "qa": "#168AAD", "sme": "#C88719",
                "owner": "#7C3AED", "coordinator": "#64748B"}


def _svg(body: str, label: str, size: int, decorative: bool = False) -> str:
    accessibility = "aria-hidden='true'" if decorative else f"role='img' aria-label='{html.escape(label, quote=True)}'"
    return (f"<svg class='avatar-svg' {accessibility} width='{int(size)}' height='{int(size)}' "
            f"viewBox='0 0 36 36' xmlns='http://www.w3.org/2000/svg'>{body}</svg>")


def system_avatar_svg(size: int = 36, *, unknown: bool = False) -> str:
    question = "<path d='M27 7c4 0 5 5 2 7l-2 1v2M27 21h.01' fill='none' stroke='#F7F5F8' stroke-width='2' stroke-linecap='round'/>" if unknown else ""
    body = ("<rect width='36' height='36' rx='8' fill='#30313A'/><rect x='8' y='8' width='17' height='6' rx='2' fill='#8D8794'/>"
            "<rect x='8' y='16' width='20' height='6' rx='2' fill='#B8B3BE'/><rect x='8' y='24' width='17' height='5' rx='2' fill='#8D8794'/>"
            "<path d='M10 19h4l2-3 3 7 2-4h5' fill='none' stroke='#36C5F0' stroke-width='1.8' stroke-linejoin='round'/>" + question)
    return _svg(body, "Board system", size)


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
        body = ("<rect width='36' height='36' rx='8' fill='#172554'/><circle cx='18' cy='18' r='5' fill='#FBBF24'/>"
                "<path d='M6 20c4-10 17-14 25-7M9 27c8 3 19-2 21-10' fill='none' stroke='#93C5FD' stroke-width='2' stroke-linecap='round'/>"
                "<circle cx='29' cy='13' r='2.5' fill='#F7F5F8'/>")
        return _svg(body, "Consultant avatar", size)
    color = _ROLE_COLORS.get(role_name)
    if color is None:
        return system_avatar_svg(size, unknown=True)
    spark = ("<g fill='#FFF3D8'><ellipse cx='18' cy='11' rx='3.4' ry='6'/><ellipse cx='18' cy='25' rx='3.4' ry='6'/>"
             "<ellipse cx='12' cy='14.5' rx='3.4' ry='6' transform='rotate(-60 12 14.5)'/><ellipse cx='24' cy='21.5' rx='3.4' ry='6' transform='rotate(-60 24 21.5)'/>"
             "<ellipse cx='24' cy='14.5' rx='3.4' ry='6' transform='rotate(60 24 14.5)'/><ellipse cx='12' cy='21.5' rx='3.4' ry='6' transform='rotate(60 12 21.5)'/></g>")
    motifs = {
        "architect": "<path d='M4 9h8M4 13h5M27 23v9M23 28h9' stroke='#C7D2FE' fill='none'/>",
        "engineer": "<path d='M9 11 5 18l4 7M27 11l4 7-4 7' stroke='#fff' stroke-width='2' fill='none'/>",
        "reviewer": "<path d='m22 24 3 3 6-8' stroke='#fff' stroke-width='2.4' fill='none'/>",
        "adversary": "<path d='M3 30 31 4v10L14 31z' fill='#7D2020' opacity='.75'/>",
        "qa": "<circle cx='18' cy='18' r='13' fill='none' stroke='#D7F6FF' stroke-width='1.5'/>",
        "sme": "<circle cx='7' cy='9' r='2' fill='#fff'/><circle cx='29' cy='27' r='2' fill='#fff'/><path d='m8 10 7 5m6 6 7 5' stroke='#fff'/>",
        "owner": "<path d='M10 9h16l-2 5H12zM13 7l5 4 5-4' fill='#FDE68A'/>",
        "coordinator": "<path d='M7 27 18 8l11 19M7 27h22' stroke='#fff' fill='none'/><circle cx='7' cy='27' r='2' fill='#fff'/><circle cx='18' cy='8' r='2' fill='#fff'/><circle cx='29' cy='27' r='2' fill='#fff'/>",
    }
    return _svg(f"<rect width='36' height='36' rx='8' fill='{color}'/>{motifs[role_name]}{spark}",
                f"{role_name.title()} avatar", size)


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
