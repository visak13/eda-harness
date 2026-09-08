"""Upload sniffing + storage helpers (design §18.1, S21).

The board never trusts a client's filename or Content-Type: the artifact's real type is
SNIFFED from the leading bytes. Only an allowlist of types is accepted, and an SVG — however
it arrives — is stored as a downloadable FILE, never an inline image, so a script-bearing SVG
can never render in the board. The 25 MB cap is enforced by the caller while it streams
(nothing oversize is ever fully read into memory or written to disk).
"""

from __future__ import annotations

import os
from pathlib import Path

MAX_UPLOAD_BYTES = 25 * 1024 * 1024  # 25 MB (design §18.1)
_SNIFF_BYTES = 4096  # enough for every magic number below and an SVG root element

# sniffed content type -> the artifact form the board records. png/jpeg/gif/webp render inline
# (form=image); everything else, SVG included, is a downloadable file (form=file).
_INLINE_IMAGE_TYPES = {"image/png", "image/jpeg", "image/gif", "image/webp"}


def uploads_dir() -> Path:
    """Where uploaded bytes live: <EDP8_DATA else EDP8_HOME>/uploads, created on demand."""
    base = os.environ.get("EDP8_DATA") or os.environ.get("EDP8_HOME", ".")
    d = Path(base) / "uploads"
    d.mkdir(parents=True, exist_ok=True)
    return d


def is_inline_image(content_type: str) -> bool:
    return content_type in _INLINE_IMAGE_TYPES


_EXT = {
    "image/png": "png", "image/jpeg": "jpg", "image/gif": "gif", "image/webp": "webp",
    "image/svg+xml": "svg", "application/pdf": "pdf", "application/zip": "zip",
    "application/json": "json", "text/markdown": "md", "text/plain": "txt",
}


def ext_for(content_type: str) -> str:
    return _EXT.get(content_type, "bin")


def _looks_textual(data: bytes) -> bool:
    if b"\x00" in data:
        return False
    try:
        data.decode("utf-8")
        return True
    except UnicodeDecodeError:
        # a truncated multibyte char at the sniff boundary is still text
        try:
            data[:-3].decode("utf-8")
            return True
        except UnicodeDecodeError:
            return False


def sniff_upload(data: bytes, filename: str = "") -> str | None:
    """The real content type from the leading bytes, or None if the type is not allowed.

    Magic numbers win over the filename (a `.png` full of script is refused as text, a `.txt`
    that is really a PDF is served as a PDF). SVG is recognised structurally and returned as
    image/svg+xml — the board stores it as a file, never an inline image.
    """
    head = data[:_SNIFF_BYTES]
    if head.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if head.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if head.startswith((b"GIF87a", b"GIF89a")):
        return "image/gif"
    if head[:4] == b"RIFF" and head[8:12] == b"WEBP":
        return "image/webp"
    if head.startswith(b"%PDF-"):
        return "application/pdf"
    if head.startswith(b"PK\x03\x04"):
        return "application/zip"
    if _looks_textual(head):
        lowered = head.lstrip()[:512].lower()
        if b"<svg" in lowered or (lowered.startswith(b"<?xml") and b"<svg" in head.lower()):
            return "image/svg+xml"  # stored as a file, never inline (design §18.1)
        ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
        if ext == "json":
            return "application/json"
        if ext in ("md", "markdown"):
            return "text/markdown"
        return "text/plain"  # md/log/txt/csv and any other utf-8 text
    return None  # binary of an unknown or disallowed type
