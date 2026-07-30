"""Convert Unicode text to a compact, deterministic hyphen-separated slug."""

from __future__ import annotations

import unicodedata

__all__ = ["slugify"]


def slugify(text: str) -> str:
    """Convert text to an NFC-normalized Unicode slug.

    Preserve Unicode letters, numbers, and their attached combining marks.
    Treat every other character, including whitespace and punctuation, as a
    separator; each consecutive separator run becomes one hyphen. The result
    has no boundary hyphens. Empty and separator-only strings return ``""``.

    Args:
        text: The string to canonicalize.

    Returns:
        The canonical, side-effect-free slug.

    Raises:
        TypeError: If text is not a string.
    """
    if not isinstance(text, str):
        raise TypeError("text must be a str")

    normalized = unicodedata.normalize("NFC", text)
    characters: list[str] = []
    separator_pending = False

    for character in normalized:
        is_mark = unicodedata.category(character).startswith("M")
        is_attached_mark = is_mark and bool(characters) and not separator_pending
        is_content = character.isalnum() or is_attached_mark
        if is_content:
            if separator_pending and characters:
                characters.append("-")
            characters.append(character)
            separator_pending = False
        elif characters:
            separator_pending = True

    return "".join(characters)
