"""Upload sniffing + storage helpers (design §18.1, S21).

The board never trusts a client's filename or Content-Type: the artifact's real type is
SNIFFED from the leading bytes. Only an allowlist of types is accepted, and an SVG — however
it arrives — is stored as a downloadable FILE, never an inline image, so a script-bearing SVG
can never render in the board. The caller streams the body to disk under the cap for the sniffed
type (`limit_for`): 25 MB, or 100 MB for a video (t-f01372d361: a 90 s 1080p product-video render is
~15–30 MB, so 100 MB leaves room for longer cuts without letting arbitrary files grow).
"""

from __future__ import annotations

from pathlib import Path
from urllib.parse import quote

from edp8 import settings

MAX_UPLOAD_BYTES = 25 * 1024 * 1024  # 25 MB (design §18.1)
MAX_VIDEO_UPLOAD_BYTES = 100 * 1024 * 1024  # 100 MB for mp4/webm (t-f01372d361)
_SNIFF_BYTES = 4096  # enough for every magic number below and an SVG root element

# sniffed content type -> the artifact form the board records. png/jpeg/gif/webp render inline
# (form=image); everything else, SVG included, is a downloadable file (form=file).
_INLINE_IMAGE_TYPES = {"image/png", "image/jpeg", "image/gif", "image/webp"}
# video plays inline in the board's <video controls> (t-f01372d361); recorded as form=file
_INLINE_VIDEO_TYPES = {"video/mp4", "video/webm"}
# ISO-BMFF major brands a browser plays as video/mp4; an image brand (avif, heic, …) or a
# QuickTime 'qt  ' file is not an mp4 video and stays refused
_MP4_BRANDS = {b"isom", b"iso2", b"iso4", b"iso5", b"iso6", b"mp41", b"mp42", b"avc1", b"M4V ", b"dash", b"mmp4"}


def uploads_dir() -> Path:
    """Where uploaded bytes live: <settings data dir>/uploads (EDP8_DATA when set), created on demand."""
    d = settings.data_dir() / "uploads"
    d.mkdir(parents=True, exist_ok=True)
    return d


def is_inline_image(content_type: str) -> bool:
    return content_type in _INLINE_IMAGE_TYPES


def is_inline_video(content_type: str) -> bool:
    return content_type in _INLINE_VIDEO_TYPES


def _sniff_video(head: bytes) -> str | None:
    """video/mp4 from an ISO-BMFF `ftyp` box with a video major brand; video/webm from an EBML
    header whose DocType is `webm` (a Matroska .mkv is not accepted)."""
    if head[4:8] == b"ftyp" and head[8:12] in _MP4_BRANDS:
        return "video/mp4"
    if head.startswith(b"\x1a\x45\xdf\xa3") and b"\x42\x82\x84webm" in head[:64]:
        return "video/webm"
    return None


def limit_for(head: bytes) -> int:
    """The byte cap for an upload whose first bytes are `head`: the video cap for mp4/webm."""
    return MAX_VIDEO_UPLOAD_BYTES if _sniff_video(head) else MAX_UPLOAD_BYTES


_EXT = {
    "image/png": "png", "image/jpeg": "jpg", "image/gif": "gif", "image/webp": "webp",
    "image/svg+xml": "svg", "application/pdf": "pdf", "application/zip": "zip",
    "application/json": "json", "text/markdown": "md", "text/plain": "txt",
    "video/mp4": "mp4", "video/webm": "webm",
}


def ext_for(content_type: str) -> str:
    return _EXT.get(content_type, "bin")


def content_disposition(disposition: str, filename: str) -> str:
    """An RFC 6266 Content-Disposition value that survives a non-Latin or quoted filename
    (finding 14). Starlette encodes response headers as latin-1, so a raw UTF-8 filename raised
    UnicodeEncodeError → the download 500'd; unescaped quotes also broke the quoted-string. We emit
    BOTH: an ASCII-only `filename="..."` fallback (quotes/backslashes escaped, every non-ASCII byte
    replaced with `_`) for legacy agents, and `filename*=UTF-8''<pct-encoded>` for the real name."""
    # Sanitise the name ONCE, so BOTH the ASCII fallback and filename* are built from a safe value
    # (qa m-97e15d2c0b): (1) reduce to a basename — a download filename must never carry path
    # segments like ../../etc/passwd; (2) drop control chars (NUL/CR/LF/DEL, < 0x20 or 0x7f) outright
    # — they are illegal in an HTTP header value (h11 LocalProtocolError → a 500), a CR/LF is a
    # header-injection vector, and even percent-encoded in filename* a control char has no place in a
    # saved filename. The real (Unicode) name still rides in filename*, percent-encoded.
    raw = (filename or "download").replace("\\", "/").rsplit("/", 1)[-1] or "download"
    name = "".join(ch for ch in raw if 32 <= ord(ch) != 127) or "download"
    ascii_fallback = "".join(
        ("_" if ord(ch) > 127 else "\\" + ch if ch in ('"', "\\") else ch)
        for ch in name
    ).strip() or "download"
    # RFC 5987/6266 ext-value: percent-encode everything but the unreserved/attr-char set.
    encoded = quote(name, safe="!#$&+-.^_`|~")
    return f'{disposition}; filename="{ascii_fallback}"; filename*=UTF-8\'\'{encoded}'


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
    video = _sniff_video(head)
    if video:
        return video
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
