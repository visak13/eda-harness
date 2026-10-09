"""Single-host MCP file access, separate from seat-local adapters.

Two sources of upload roots, both behind the same loopback/credential guards:
- an operator policy (EDP8_HTTP_UPLOAD_MODE=single-host + a policy JSON) enrolls participants/roots and is
  authoritative whenever it is set;
- with the mode UNSET, a loopback single-host deployment lets any authenticated agent seat upload from the
  agent home, because the pool pins every seat's cwd there (S15, p-a3ae2179).
EDP8_HTTP_UPLOAD_MODE=off disables both. Authentication is rechecked by an existing-token-only board
endpoint before any requested file is resolved/opened.

A public URL (Remote access on) does not switch uploads off (RC2 F3, architect m-1f09a47214): tailscale
serve proxies 443 to the loopback BOARD only, never this MCP port, and a proxied request is refused per call
anyway (mcp_server: a Forwarded/X-Forwarded-* header or a non-loopback peer → unavailable). What keeps it
off is a non-loopback MCP bind or a remote board URL.
"""
from __future__ import annotations

from dataclasses import dataclass, field
import ipaddress
import json
import os
from pathlib import Path
import tempfile
from urllib.parse import urlsplit

from edp8 import settings

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
            'hint': 'needs a loopback single-host install, your seat token and an absolute path inside the agent home '
                    '(or the operator-configured roots)'}


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


_SECRET_NAMES = {n.lower() for n in settings.SECRET_FILES} | {'.netrc', 'id_rsa', 'id_ed25519', 'credentials'}
_SECRET_SUFFIXES = ('.pem', '.key', '.pfx', '.p12')
_SECRET_DIRS = {'secrets', '.ssh', '.aws', '.gnupg', '.logs', '.run'}


def _forbidden(path: Path, root: Path) -> str | None:
    """Why an automatic-root upload of `path` is refused (secret-looking name, a secrets dir, the DB), else None.
    The agent home is the pool's seat cwd, and in a source checkout it also holds .env, tokens.json and
    .data (the DB): only .data/codex-images is shareable there. Defence in depth; the board's secret screen
    still runs on finalise."""
    name = path.name.lower()
    if name.startswith('.env') or name in _SECRET_NAMES or name.endswith(_SECRET_SUFFIXES) or name.startswith('edp8.db'):
        return 'that file name looks like a secret or the board database'
    if any(part.lower() in _SECRET_DIRS for part in path.parts):
        return 'that folder holds secrets, logs or run state'
    try:
        secrets = settings.secrets_dir().resolve()
        data = settings.data_dir().resolve()
        # EDP_HOME layout: the secrets dir is the home itself (an ancestor of the upload root or the data
        # dir), so refuse only its secret files there; installed, the whole secrets dir stays refused.
        if root.is_relative_to(secrets) or data.is_relative_to(secrets):
            refused = [secrets / n for n in settings.SECRET_FILES]
        else:
            refused = [secrets]
        for secret in (*refused, Path(settings.get('EDP8_TOKENS')), settings.admin_token_file()):
            if path.is_relative_to(secret.resolve()):
                return 'that path is the board secrets'
        if (data != root and data.is_relative_to(root) and path.is_relative_to(data)
                and not path.is_relative_to(data / 'codex-images')):
            return 'only .data/codex-images may be uploaded from the board data folder'
    except (OSError, ValueError):
        return 'that path could not be checked'
    return None


def _agent_home_root() -> Path:
    """The canonical agent home, pinned once at startup (a later junction swap is not followed)."""
    home = settings.agent_home().resolve(strict=True)
    if not home.is_dir():
        raise ValueError('agent home is not a directory')
    for broad in (Path.home().resolve(), Path(tempfile.gettempdir()).resolve(), Path(home.anchor)):
        if broad.is_relative_to(home):
            raise ValueError('broad root forbidden')
    return home


@dataclass(frozen=True)
class HttpUploadPolicy:
    roots: dict[str, tuple[Path, ...]] = field(default_factory=dict)
    enabled: bool = False
    auto_roots: tuple[Path, ...] = ()

    @classmethod
    def from_environment(cls, board_url: str):
        """Read trusted config only at server startup; any invalid/remote config disables."""
        mode = settings.get('EDP8_HTTP_UPLOAD_MODE')
        if mode not in (None, '', 'single-host'):
            return cls()
        try:
            parsed = urlsplit(board_url)
            _ = parsed.port  # validate malformed URLs without contacting any host
        except ValueError:
            return cls()
        if (not _loopback(settings.get('EDP8_MCP_HOST'))
                or parsed.scheme not in ('http', 'https') or not _loopback(parsed.hostname)
                or parsed.username or parsed.password):
            return cls()
        if not mode:  # unset: the loopback single-host default, agent home only (S15)
            try:
                return cls(enabled=True, auto_roots=(_agent_home_root(),))
            except (OSError, ValueError):
                return cls()
        try:
            config = settings.get('EDP8_HTTP_UPLOAD_POLICY')
            if config is None or not config.is_absolute():
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
        if self.auto_roots:
            if authorization['value'].get('type') != 'agent':
                return _error('scope', 'automatic single-host uploads are for agent seats; people use the web UI')
            roots = self.auto_roots
        else:
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
        if self.auto_roots:
            try:
                why = _forbidden(Path(os.path.realpath(candidate)), root) or _forbidden(candidate, root)
            except (OSError, ValueError):
                why = 'that path could not be checked'
            if why:
                return _error('upload_refused', why)
        # Request-scoped client only; no global root or identity state is mutated.
        client.workspace_root = root
        try:
            return client.artifact_upload(path, note, _pinned_root=True)
        except BoardUnreachable:
            return _error('unavailable', 'board upload service unavailable')
        finally:
            client.workspace_root = None
