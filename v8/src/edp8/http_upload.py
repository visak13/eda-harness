"""Default-off single-host MCP file access, separate from seat-local adapters.

Only an operator policy enrolls participants/roots. Authentication is rechecked by
an existing-token-only board endpoint before any requested file is resolved/opened.
"""
from __future__ import annotations

from dataclasses import dataclass, field
import ipaddress
import json
import os
from pathlib import Path
import tempfile
from urllib.parse import urlsplit

from .client import BoardUnreachable


def _loopback(host: str | None) -> bool:
    if host == 'localhost':
        return True
    try:
        address = ipaddress.ip_address(host or '')
        return address.is_loopback or bool(getattr(address, 'ipv4_mapped', None) and address.ipv4_mapped.is_loopback)
    except ValueError:
        return False


def _error(code: str, message: str) -> dict:
    return {'ok': False, 'error': {'code': code, 'message': message},
            'hint': 'requires operator-enabled single-host policy, an enrolled authenticated seat and an absolute allowed file path'}


def _root(value: str) -> Path:
    if not isinstance(value, str):
        raise ValueError('root must be a string')
    path = Path(value)
    if not path.is_absolute() or '..' in path.parts or path.drive.startswith('\\\\'):
        raise ValueError('root must be absolute')
    canonical = path.resolve(strict=True)
    if path != canonical or not canonical.is_dir():
        raise ValueError('root must already be canonical directory')
    # A whole home, system temp, drive root, or any ancestor of them is never a workspace.
    for broad in (Path.home().resolve(), Path(tempfile.gettempdir()).resolve(), Path(path.anchor)):
        if broad.is_relative_to(canonical):
            raise ValueError('broad root forbidden')
    return canonical


@dataclass(frozen=True)
class HttpUploadPolicy:
    roots: dict[str, tuple[Path, ...]] = field(default_factory=dict)
    enabled: bool = False

    @classmethod
    def from_environment(cls, board_url: str):
        """Read trusted config only at server startup; any invalid/remote config disables."""
        if os.environ.get('EDP8_HTTP_UPLOAD_MODE') != 'single-host':
            return cls()
        try:
            parsed = urlsplit(board_url)
            _ = parsed.port  # validate malformed URLs without contacting any host
        except ValueError:
            return cls()
        if (os.environ.get('EDP8_PUBLIC_URL') or not _loopback(os.environ.get('EDP8_MCP_HOST', '127.0.0.1'))
                or parsed.scheme not in ('http', 'https') or not _loopback(parsed.hostname)
                or parsed.username or parsed.password):
            return cls()
        try:
            config = Path(os.environ.get('EDP8_HTTP_UPLOAD_POLICY', ''))
            if not config.is_absolute():
                return cls()
            with config.open('rb') as file:
                raw = file.read(65537)
            if len(raw) > 65536:
                return cls()
            data = json.loads(raw)
            if data['version'] != 1 or not isinstance(data['seats'], dict) or not data['seats']:
                return cls()
            workspace = _root(data['workspace_root'])
            roots = {}
            scratch_roots = []
            for participant, seat in data['seats'].items():
                if not isinstance(participant, str) or not participant or not isinstance(seat, dict):
                    return cls()
                allowed = [workspace]
                if seat.get('scratch_root') is not None:
                    scratch = _root(seat['scratch_root'])
                    if scratch.is_relative_to(workspace) or workspace.is_relative_to(scratch):
                        return cls()
                    if any(scratch.is_relative_to(r) or r.is_relative_to(scratch) for r in scratch_roots):
                        return cls()
                    scratch_roots.append(scratch)
                    allowed.append(scratch)
                roots[participant] = tuple(allowed)
            # Do not let a seat rewrite its policy via its writable/uploadable workspace.
            config = config.resolve(strict=True)
            if any(config.is_relative_to(r) for allowed in roots.values() for r in allowed):
                return cls()
            return cls(roots=roots, enabled=True)
        except (OSError, ValueError, KeyError, TypeError):
            return cls()

    def upload(self, client, path: str, note: str, peer: str | None) -> dict:
        if not self.enabled or not _loopback(peer):
            return _error('unavailable', 'single-host HTTP uploads disabled or request is not local')
        # Missing request credentials must NOT fall back to the proxy process's token.
        if not client.participant or not client.token:
            return _error('unauthorized', 'a configured seat credential is required for HTTP file access')
        try:
            authorization = client.upload_authorize()
        except BoardUnreachable:
            return _error('unavailable', 'board authorization service unavailable')
        if not authorization.get('ok'):
            return _error('unauthorized', 'board refused HTTP upload authorization')
        participant = authorization['value']['participant_id']
        roots = self.roots.get(participant)
        if not roots:
            return _error('scope', 'authenticated participant is not enrolled for HTTP file access')
        candidate = Path(path)
        if not candidate.is_absolute() or '..' in candidate.parts:
            return _error('upload_refused', 'HTTP upload requires an absolute path without parent traversal')
        # This is a lexical check only; workspace_file performs canonical and opened-handle checks.
        root = next((r for r in roots if candidate.is_relative_to(r)), None)
        if root is None:
            return _error('upload_refused', 'file is outside the configured roots for this seat')
        # Request-scoped client only; no global root or identity state is mutated.
        client.workspace_root = root
        try:
            return client.artifact_upload(path, note, _pinned_root=True)
        except BoardUnreachable:
            return _error('unavailable', 'board upload service unavailable')
        finally:
            client.workspace_root = None
