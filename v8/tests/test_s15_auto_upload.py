"""S15 (p-a3ae2179 + dups): a same-host pool seat uploads over MCP with NO operator policy, from the agent home.

Roots come from the agent home (the pool pins every seat's cwd there). Every S7 guard stays: loopback peer,
no forwarding headers, loopback bind/board, a verified agent token, opened-handle containment,
the size cap. An operator policy, when set, stays authoritative.
"""
import json
import os
import subprocess

import pytest
from fastapi.testclient import TestClient
from test_context_tools import board, client, rig  # noqa: F401  (fixtures)
from test_mcp_http import _Server, _call, _free_port, _run
from edp8.client import BoardClient
from edp8.http_upload import HttpUploadPolicy
from edp8.mcp_server import build_http_app
from edp8.service import create_app

LOCAL = 'http://127.0.0.1:1234'


@pytest.fixture
def auto(board, client, rig, tmp_path, monkeypatch):  # noqa: F811
    home = tmp_path / 'agent-home'
    (home / '.data' / 'codex-images' / 't-1').mkdir(parents=True)
    (home / '.data' / 'uploads').mkdir()
    (home / '.logs').mkdir()
    (home / 'notes').mkdir()
    (home / 'notes' / 'proof.txt').write_text('same-host MCP proof')
    (home / '.data' / 'codex-images' / 't-1' / 'nation-01.png').write_bytes(b'\x89PNG\r\n\x1a\n' + bytes(64))
    (home / '.data' / 'edp8.db').write_bytes(b'SQLite format 3')
    (home / '.data' / 'uploads' / 'staged.txt').write_text('another artifact')
    (home / '.logs' / 'seat.log').write_text('log with a token')
    (home / '.env').write_text('EDP8_ADMIN_TOKEN=live')
    outside = tmp_path / 'project'
    outside.mkdir()
    (outside / 'elsewhere.txt').write_text('not under the agent home')
    tokens = home / 'tokens.json'
    tokens.write_text(json.dumps({'owner': 'owner-secret', 'agents': {'eng': 'eng-secret', 'arch': 'arch-secret'}}))
    monkeypatch.setenv('EDP_AGENT_HOME', str(home))
    monkeypatch.setenv('EDP8_DATA', str(home / '.data'))
    monkeypatch.setenv('EDP8_TOKENS', str(tokens))
    monkeypatch.setenv('EDP8_MCP_HOST', '127.0.0.1')
    monkeypatch.setenv('EDP8_TOKEN', 'eng-secret')
    for name in ('EDP8_HTTP_UPLOAD_MODE', 'EDP8_HTTP_UPLOAD_POLICY', 'EDP8_PUBLIC_URL'):
        monkeypatch.delenv(name, raising=False)
    app = TestClient(create_app(board, admin_token='t'))
    return {'home': home, 'outside': outside, 'tokens': tokens, 'rig': rig, 'app': app}


def _policy():
    return HttpUploadPolicy.from_environment(LOCAL)


def test_automatic_root_is_the_agent_home_and_pins_it(auto):
    policy = _policy()
    assert policy.enabled and policy.roots == {} and policy.auto_roots == (auto['home'].resolve(),)


@pytest.mark.parametrize('public', [False, True])
def test_same_host_seat_uploads_over_mcp_without_operator_policy(board, auto, monkeypatch, public):
    """RC2 F3 (p-320be927, p-5d1361d2): with Remote access on (a public URL in the env) a loopback seat
    still uploads; every per-request guard below still refuses."""
    if public:
        monkeypatch.setenv('EDP8_PUBLIC_URL', 'https://board.example.ts.net')
    bp, mp = _free_port(), _free_port()
    monkeypatch.setenv('EDP8_BOARD_URL', f'http://127.0.0.1:{bp}')
    url = f'http://127.0.0.1:{mp}/mcp/engineer'

    def call(name, token='eng-secret', participant='eng', headers=None, **args):
        sent = {'X-Participant': participant, **(headers or {})}
        if token is not None:
            sent['X-Token'] = token
        _, result = _run(_call(url, sent, name, **args))
        return json.loads(result.content[0].text)

    home, t1 = auto['home'], auto['rig']['t1']['id']
    with _Server(create_app(board, admin_token='t'), bp), _Server(build_http_app(roles=['engineer']), mp):
        proof = str(home / 'notes' / 'proof.txt')
        out = call('artifact_upload', path=proof)
        assert out['ok'], out
        assert out['value']['created_by'] == 'eng' and out['value']['staged']
        sent = call('message_send', ticket_id=t1, kind='note', text='attached proof', artifacts=[out['value']['id']])
        assert sent['ok'], sent
        assert not call('artifact_read', id=out['value']['id'])['value']['staged']
        image = call('artifact_upload', path=str(home / '.data' / 'codex-images' / 't-1' / 'nation-01.png'))
        assert image['ok'], image
        # refusals, none of them reaching the file
        assert call('artifact_upload', path=proof, headers={'X-Forwarded-For': '127.0.0.1'})['error']['code'] == 'unavailable'
        assert call('artifact_upload', token=None, path=proof)['error']['code'] == 'unauthorized'
        assert call('artifact_upload', token='wrong', path=proof)['error']['code'] == 'unauthorized'
        assert call('artifact_upload', participant='missing', path=proof)['error']['code'] == 'unauthorized'
        assert call('artifact_upload', path=str(auto['outside'] / 'elsewhere.txt'))['error']['code'] == 'upload_refused'
        assert call('artifact_upload', path='notes/proof.txt')['error']['code'] == 'upload_refused'
        assert call('artifact_upload', path=str(home / 'notes' / '..' / 'notes' / 'proof.txt'))['error']['code'] == 'upload_refused'
        assert call('artifact_upload', path=proof + ':secret')['error']['code'] == 'upload_refused'
        for secret in ('.env', 'tokens.json', '.data/edp8.db', '.data/uploads/staged.txt', '.logs/seat.log'):
            refused = call('artifact_upload', path=str(home / secret))
            assert refused['error']['code'] == 'upload_refused', (secret, refused)


def test_secrets_are_refused_before_the_file_is_opened(auto, monkeypatch):
    import edp8.local_upload as local

    def forbidden(*args, **kw):
        pytest.fail('a refused request reached file opening')
    monkeypatch.setattr(local, 'workspace_file', forbidden)
    seat = BoardClient(participant='eng', token='eng-secret', client=auto['app'])
    policy = _policy()
    for rel in ('.env', 'tokens.json', '.data/edp8.db', '.data/uploads/staged.txt', '.logs/seat.log'):
        out = policy.upload(seat, str(auto['home'] / rel), '', '127.0.0.1')
        assert out['error']['code'] == 'upload_refused', rel
    assert policy.upload(seat, str(auto['outside'] / 'elsewhere.txt'), '', '127.0.0.1')['error']['code'] == 'upload_refused'
    assert policy.upload(seat, str(auto['home'] / 'notes' / 'proof.txt'), '', '192.0.2.10')['error']['code'] == 'unavailable'
    assert HttpUploadPolicy().upload(seat, str(auto['home'] / 'notes' / 'proof.txt'), '', '127.0.0.1')['error']['code'] == 'unavailable'


def test_a_person_cannot_use_the_automatic_root(auto):
    out = _policy().upload(BoardClient(participant='owner', token='owner-secret', client=auto['app']),
                           str(auto['home'] / 'notes' / 'proof.txt'), '', '127.0.0.1')
    assert not out['ok'] and out['error']['code'] == 'scope'


def test_home_junction_escape_is_refused(auto):
    if os.name != 'nt':
        pytest.skip('Windows junction test')
    junction = auto['home'] / 'escape'
    made = subprocess.run(['cmd', '/c', 'mklink', '/J', str(junction), str(auto['outside'])], capture_output=True)
    assert made.returncode == 0
    try:
        out = _policy().upload(BoardClient(participant='eng', token='eng-secret', client=auto['app']),
                               str(junction / 'elsewhere.txt'), '', '127.0.0.1')
        assert out['error']['code'] == 'upload_refused'
    finally:
        junction.rmdir()


@pytest.mark.parametrize('change', ['off', 'remote_bind', 'remote_board', 'invalid_url', 'no_home', 'broad_home'])
def test_unsafe_deployments_stay_off(auto, monkeypatch, tmp_path, change):
    url = LOCAL
    if change == 'off':
        monkeypatch.setenv('EDP8_HTTP_UPLOAD_MODE', 'off')
    monkeypatch.setenv('EDP8_PUBLIC_URL', 'https://board.example.com')  # RC2 F3: never the reason it is off
    if change == 'remote_bind':
        monkeypatch.setenv('EDP8_MCP_HOST', '0.0.0.0')
    if change == 'remote_board':
        url = 'https://board.example.com'
    if change == 'invalid_url':
        url = 'http://[invalid'
    if change == 'no_home':
        monkeypatch.setenv('EDP_AGENT_HOME', str(tmp_path / 'missing'))
    if change == 'broad_home':
        monkeypatch.setenv('EDP_AGENT_HOME', str(os.path.expanduser('~')))
    assert not HttpUploadPolicy.from_environment(url).enabled


def test_operator_policy_stays_authoritative(auto, tmp_path, monkeypatch):
    workspace = tmp_path / 'workspace'
    workspace.mkdir()
    (workspace / 'ok.txt').write_text('operator root')
    config = tmp_path / 'operator-policy.json'
    config.write_text(json.dumps({'version': 1, 'workspace_root': str(workspace.resolve()), 'seats': {'arch': {}}}))
    monkeypatch.setenv('EDP8_HTTP_UPLOAD_MODE', 'single-host')
    monkeypatch.setenv('EDP8_HTTP_UPLOAD_POLICY', str(config))
    policy = _policy()
    assert policy.enabled and policy.auto_roots == ()
    seat = BoardClient(participant='eng', token='eng-secret', client=auto['app'])
    # eng is not enrolled: the agent home is NOT a fallback while an operator policy is set
    assert policy.upload(seat, str(auto['home'] / 'notes' / 'proof.txt'), '', '127.0.0.1')['error']['code'] == 'scope'
    config.write_text('{')
    assert not _policy().enabled  # a broken operator policy fails closed, it does not fall back to automatic roots


_LAYOUT_ENV = ('EDP_HOME', 'EDP8_HOME', 'EDP_CONFIG_DIR', 'EDP8_DATA', 'EDP_AGENT_HOME', 'EDP8_TOKENS', 'EDP8_ADMIN_TOKEN')


@pytest.mark.parametrize('nested', [False, True])
def test_edp_home_layout_refuses_only_the_secret_files(tmp_path, monkeypatch, nested):
    """D8 (m-aea1c99f5f): with EDP_HOME the secrets dir IS the home, so refusing the whole secrets dir refused
    every upload from the agent home. Only the registry's secret files are refused there."""
    from edp8 import settings
    from edp8.http_upload import _forbidden
    for name in _LAYOUT_ENV:
        monkeypatch.delenv(name, raising=False)
    home = tmp_path / 'home'
    agent = home / 'agent-home' if nested else home
    (agent / 'notes').mkdir(parents=True)
    monkeypatch.setenv('EDP_HOME', str(home))
    monkeypatch.setenv('EDP_AGENT_HOME', str(agent))
    assert settings.secrets_dir().resolve() == home.resolve()
    root = agent.resolve()
    proof = agent / 'notes' / 'proof.txt'
    proof.write_text('agent-home proof')
    assert _forbidden(proof.resolve(), root) is None
    for name in settings.SECRET_FILES:
        (home / name).write_text('secret')
        assert _forbidden((home / name).resolve(), root), name
    assert {'tokens.json', 'admin.token'} <= set(settings.SECRET_FILES)


def test_installed_layout_still_refuses_the_whole_secrets_dir(tmp_path, monkeypatch):
    from edp8 import settings
    from edp8.http_upload import _forbidden
    for name in _LAYOUT_ENV:
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv('EDP_CONFIG_DIR', str(tmp_path / 'config'))
    monkeypatch.setenv('EDP8_DATA', str(tmp_path / 'data'))
    agent = tmp_path / 'data' / 'agent-home'
    (agent / 'notes').mkdir(parents=True)
    monkeypatch.setenv('EDP_AGENT_HOME', str(agent))
    secrets = settings.secrets_dir()
    assert secrets.resolve() == (tmp_path / 'config' / 'secrets').resolve()
    secrets.mkdir(parents=True)
    plain = secrets / 'notes.txt'
    plain.write_text('not a secret name, but in the secrets dir')
    (agent / 'notes' / 'proof.txt').write_text('agent-home proof')
    assert _forbidden(plain.resolve(), agent.resolve())  # the whole secrets dir, any file name
    assert _forbidden((agent / 'notes' / 'proof.txt').resolve(), agent.resolve()) is None
