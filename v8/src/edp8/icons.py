"""Small, dependency-free inline SVG icons for the edp8 UI."""
from __future__ import annotations

import html


_ICONS = {
    # Navigation and core.
    "inbox": "<path d='M4 5.5h16v13H4zM4 14h4l1.5 2h5l1.5-2h4M9 3.5h6M12 3.5v5m0 0-2-2m2 2 2-2'/>",
    "epic": "<path d='M5 3v18M5 6h3M5 12h3M5 18h3'/><rect x='8' y='4' width='11' height='5' rx='1.5'/><rect x='8' y='10' width='11' height='5' rx='1.5'/><rect x='8' y='16' width='11' height='4' rx='1.5'/>",
    "api-reference": "<path d='M7 3.5h8l3 3V20H7zM15 3.5V7h3M4 8H2.5v8H4M21 8h1.5v8H21M10 12h4'/><circle cx='16.5' cy='12' r='1.25'/>",
    "thread": "<path d='M3 5.5h12v8H9l-3.5 3v-3H3zM9 9h12v8h-2.5v3L15 17H9z'/>",
    "document": "<path d='M6 3h8l4 4v14H6zM14 3v5h4M9 12h6M9 16h6'/>",
    "ticket": "<path d='M5 4h15v16H5v-5a2 2 0 0 0 0-4V4zM9 9h7'/>",

    # Ticket kinds.
    "ticket-epic": "<path d='M4 3h16v18H4v-5a2 2 0 0 0 0-4V3z'/><rect x='8' y='7' width='8' height='3' rx='1'/><rect x='8' y='13' width='8' height='3' rx='1'/>",
    "story": "<path d='M5 4h15v15H12l-3.5 3v-3H5v-4a2 2 0 0 0 0-4V4zM9 9h7'/>",
    "task": "<path d='M5 4h15v16H5v-5a2 2 0 0 0 0-4V4zM9 12l2 2 5-6'/>",

    # Gates.
    "gate": "<path d='M5 20V7h3v13M16 20V7h3v13M8 10h8M10 7h4'/>",
    "design-sign-off": "<path d='M4 20V7h3v13M17 20V7h3v13M7 10h10M8 17 16.5 8.5 19 11l-8.5 8.5-3 .5z'/>",
    "poc": "<path d='M4 20V7h3v13M17 20V7h3v13M7 10h10M8 15h2l1.5-3 2.5 6 1.5-3H18'/>",
    "demo": "<path d='M4 20V7h3v13M17 20V7h3v13M7 10h10'/><path d='m10 13 5 3-5 3z'/>",
    "adversarial": "<path d='M4 20V7h3v13M17 20V7h3v13M7 10h3M14 10h3M8 18 16 8M10 8l-2 2M16 16l-2 2'/>",
    "budget": "<path d='M4 20V7h3v13M17 20V7h3v13M7 10h10M9 13h6M9 16h6M9 19h6'/>",
    "acceptance": "<path d='M4 20V7h3v13M17 20V7h3v13M7 10h10v10H7M9.5 15l2 2 4-5'/>",

    # Event types.
    "message-sent": "<path d='M3 6h10v8H8l-3 2.5V14H3zM15 10h4m-2-2 2 2-2 2'/><circle cx='21' cy='10' r='1'/>",
    "status-changed": "<path d='M3 17h5v-5h5V7h4M15 5h5v5h-5z'/>",
    "gate-opened": "<path d='M4 21V9h3v12M17 21V9h3v12M8 7l8-3M10 3h6v6'/>",
    "gate-answered": "<path d='M4 21V8h3v13M17 21V8h3v13M7 11h10v10H7'/><circle cx='12' cy='16' r='1.5'/>",
    "assigned": "<path d='M3 5h11v14H3v-4a2 2 0 0 0 0-4V5zM14 12h3'/><circle cx='19' cy='8' r='2'/><path d='M16 19c.4-2.4 1.4-3.5 3-3.5s2.6 1.1 3 3.5'/>",
    "document-updated": "<path d='M4 3h8l3 3v8H4zM12 3v4h3M8 10h3M16 15a4 4 0 1 1-1 4m1-4v3h-3'/>",
    "shell-dead": "<rect x='3' y='4' width='18' height='16' rx='2'/><path d='m6 9 2 2-2 2M10 15h2l1-4 2 7 1-3h2M12 11l2 4'/>",
    "shell-stalled": "<rect x='3' y='4' width='18' height='16' rx='2'/><path d='m6 9 2 2-2 2M10 15h2l1-4 1 4h1M17 12v5M20 12v5'/>",
    "ticket-created": "<path d='M4 5h13v15H4v-4a2 2 0 0 0 0-4V5zM15 7h6M18 4v6'/>",

    # Empty states.
    "inbox-clear": "<path d='M3 7h18v12H3zM3 14h5l1.5 2h5l1.5-2h5M7 4h10'/>",
    "no-open-gates": "<path d='M4 20V8h3v12M17 20V8h3v12M7 17h10M10 5h4M12 5v8'/>",
    "no-messages": "<path d='M3 6h11v7H8l-3 2.5V13H3zM10 10h11v7h-2v2.5L16 17h-6z'/>",
    "no-epics": "<path d='M6 3v18M6 7h3M6 12h3M6 17h3M12 6h7M12 11h7M12 16h7' stroke-dasharray='2 2'/>",
    "no-documents": "<path d='M5 5h8l4 4v12H5zM13 5v5h4M8 3h8l3 3v12'/>",
    "no-criteria": "<rect x='3' y='5' width='5' height='5' rx='1'/><path d='M11 7.5h10M3 15h18' stroke-dasharray='2 2'/>",
}

_ALIASES = {
    "epics": "epic",
    "doc": "document",
    "api": "api-reference",
    "api-ref": "api-reference",
    "generic-gate": "gate",
    "gate-generic": "gate",
    "epic-ticket": "ticket-epic",
    "epic-kind": "ticket-epic",
    "story-ticket": "story",
    "ticket-story": "story",
    "task-ticket": "task",
    "ticket-task": "task",
    "gate-design-sign-off": "design-sign-off",
    "design-gate": "design-sign-off",
    "gate-poc": "poc",
    "gate-demo": "demo",
    "gate-adversarial": "adversarial",
    "gate-budget": "budget",
    "gate-acceptance": "acceptance",
    "quiet-project": "no-messages",
    "no-messages-quiet-project": "no-messages",
}


def icon(name: str, size: int = 16, label: str | None = None) -> str:
    """Return an inline SVG icon, falling back to ``ticket`` for unknown names."""
    normalized = str(name).strip().lower().replace("_", "-").replace(" ", "-")
    normalized = _ALIASES.get(normalized, normalized)
    drawing = _ICONS.get(normalized, _ICONS["ticket"])
    dimension = int(size)
    if dimension <= 0:
        raise ValueError("icon size must be positive")
    if label is None:
        accessibility = "aria-hidden='true'"
    else:
        accessibility = f"role='img' aria-label='{html.escape(str(label), quote=True)}'"
    return (
        f"<svg {accessibility} width='{dimension}' height='{dimension}' viewBox='0 0 24 24' "
        "fill='none' stroke='currentColor' stroke-width='1.75' "
        f"stroke-linecap='round' stroke-linejoin='round'>{drawing}</svg>"
    )
