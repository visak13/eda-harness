"""File upload boundary for seat-local adapters or an explicit single-host policy.

The root is supplied by the local harness, never a model tool argument. Verify the
opened handle as well as the resolved name to close symlink/junction swap races.
"""
from __future__ import annotations

import contextlib
import json
import os
from pathlib import Path
import stat
import sys

from .uploads import MAX_UPLOAD_BYTES


class UploadRefused(ValueError):
    pass


def _handle_path(file) -> Path:
    if os.name == 'nt':
        import ctypes
        import msvcrt
        from ctypes import wintypes
        fn = ctypes.WinDLL('kernel32', use_last_error=True).GetFinalPathNameByHandleW
        fn.argtypes = [wintypes.HANDLE, wintypes.LPWSTR, wintypes.DWORD, wintypes.DWORD]
        fn.restype = wintypes.DWORD
        buf = ctypes.create_unicode_buffer(32768)
        n = fn(msvcrt.get_osfhandle(file.fileno()), buf, len(buf), 0)
        if not n or n >= len(buf):
            raise UploadRefused('cannot verify opened file handle')
        path = buf.value
        if path.startswith('\\\\?\\UNC\\'):
            path = '\\\\' + path[8:]
        elif path.startswith('\\\\?\\'):
            path = path[4:]
        return Path(path)
    fd = Path(f'/proc/self/fd/{file.fileno()}')
    if not fd.exists():
        raise UploadRefused('this platform has no supported opened-handle verifier')
    return fd.resolve(strict=True)


@contextlib.contextmanager
def workspace_file(root: Path, path: str, *, pinned_root: bool = False):
    # HTTP policy roots were canonicalized at startup. Do not re-resolve one to a
    # different location if its directory/ancestor is later replaced by a junction.
    if not pinned_root:
        root = root.resolve(strict=True)
    candidate = (root / path).resolve(strict=True)
    if not candidate.is_relative_to(root):
        raise UploadRefused('file is outside the seat workspace')
    if os.name == 'nt' and ':' in str(candidate)[2:]:
        raise UploadRefused('alternate streams are not workspace files')
    # Nonblocking prevents a FIFO/device path from hanging before fstat on POSIX.
    fd = os.open(candidate, os.O_RDONLY | getattr(os, 'O_NONBLOCK', 0) | getattr(os, 'O_BINARY', 0))
    with os.fdopen(fd, 'rb') as file:
        info = os.fstat(file.fileno())
        if not stat.S_ISREG(info.st_mode):
            raise UploadRefused('upload must be a regular file')
        if not _handle_path(file).is_relative_to(root):
            raise UploadRefused('opened handle escaped the seat workspace')
        if info.st_size > MAX_UPLOAD_BYTES:
            raise UploadRefused('file exceeds the 25 MB upload limit')
        yield file, candidate.name


class BoundedFile:
    """httpx multipart stream wrapper; cap reads even if a writer grows the file."""
    def __init__(self, file):
        self.file = file
        self.sent = 0

    def read(self, size=-1):
        size = min(size if size >= 0 else 65536, 65536, MAX_UPLOAD_BYTES - self.sent + 1)
        data = self.file.read(size)
        self.sent += len(data)
        if self.sent > MAX_UPLOAD_BYTES:
            raise UploadRefused('file grew beyond the 25 MB upload limit')
        return data


def main():
    """JSON stdin/stdout adapter for a trusted local harness; no credentials on argv."""
    from .client import BoardClient
    try:
        args = json.loads(sys.stdin.read(65536))
        root = os.environ.get('EDP8_UPLOAD_ROOT')
        client = BoardClient(workspace_root=Path(root) if root else None)
        out = client.artifact_upload(args['path'], args.get('note', ''))
    except (ValueError, KeyError, OSError) as exc:
        out = {'ok': False, 'error': {'code': 'upload_refused', 'message': str(exc)}, 'hint': 'check the local upload arguments'}
    print(json.dumps(out))


if __name__ == '__main__':
    main()
