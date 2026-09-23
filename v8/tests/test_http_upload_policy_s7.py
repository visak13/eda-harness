"""Single-host shared MCP uploads; isolated servers and operator policy only."""
import json
import os
from pathlib import Path
import subprocess

import pytest
from fastapi.testclient import TestClient
from test_context_tools import board, client, rig
from test_mcp_http import stack, _run, _call, _Server, _free_port
from edp8.client import BoardClient
from edp8.http_upload import HttpUploadPolicy
from edp8.mcp_server import build_http_app
from edp8.service import create_app


def test_http_upload_disabled_baseline(stack):
    _, result = _run(_call(stack['mcp'] + '/mcp/engineer', {'X-Participant': 'eng.s1'},
                           'artifact_upload', path='C:/not-opened.txt'))
    out = json.loads(result.content[0].text)
    assert not out['ok'] and out['error']['code'] == 'unavailable'


@pytest.fixture
def configured(board, client, rig, tmp_path, monkeypatch):
    workspace = tmp_path / 'workspace'; workspace.mkdir()
    scratch = tmp_path / 'scratch-eng'; scratch.mkdir()
    other = tmp_path / 'scratch-arch'; other.mkdir()
    home = tmp_path / 'board'; home.mkdir()
    (workspace / 'proof.txt').write_text('HTTP MCP proof')
    (scratch / 'seat.txt').write_text('my scratch')
    (other / 'private.txt').write_text('other seat')
    tokens = home / 'tokens.json'
    tokens.write_text(json.dumps({'owner': 'owner-secret', 'agents': {'eng': 'eng-secret', 'arch': 'arch-secret'}}))
    config = tmp_path / 'operator-policy.json'
    data = {'version': 1, 'workspace_root': str(workspace.resolve()),
            'seats': {'eng': {'scratch_root': str(scratch.resolve())}, 'arch': {'scratch_root': str(other.resolve())}}}
    config.write_text(json.dumps(data))
    monkeypatch.setenv('EDP8_HOME', str(home))
    monkeypatch.setenv('EDP8_TOKENS', str(tokens))
    monkeypatch.setenv('EDP8_HTTP_UPLOAD_MODE', 'single-host')
    monkeypatch.setenv('EDP8_HTTP_UPLOAD_POLICY', str(config))
    monkeypatch.setenv('EDP8_MCP_HOST', '127.0.0.1')
    monkeypatch.setenv('EDP8_TOKEN', 'eng-secret')  # proxy token must not fill missing request credentials
    monkeypatch.delenv('EDP8_PUBLIC_URL', raising=False)
    # create_app pins its tokens file at build time (808a062, incident m-c31573e1a2), so the `client` app
    # (built before this fixture set EDP8_TOKENS) never sees these secrets: tests that need the board to
    # accept eng's token use `app`, built over the same board after the env is in place.
    app = TestClient(create_app(board, admin_token='t'))
    return {'workspace': workspace, 'scratch': scratch, 'other': other, 'config': config,
            'data': data, 'tokens': tokens, 'rig': rig, 'app': app}


def test_real_http_upload_attach_and_identity(board, configured, monkeypatch):
    bp, mp = _free_port(), _free_port()
    monkeypatch.setenv('EDP8_BOARD_URL', f'http://127.0.0.1:{bp}')
    url = f'http://127.0.0.1:{mp}/mcp/engineer'
    def call(name, token='eng-secret', participant='eng', **args):
        headers = {'X-Participant': participant}
        if token is not None:
            headers['X-Token'] = token
        _, result = _run(_call(url, headers, name, **args))
        return json.loads(result.content[0].text)
    with _Server(create_app(board, admin_token='t'), bp), _Server(build_http_app(roles=['engineer']), mp):
        proof = str(configured['workspace'] / 'proof.txt')
        _, forwarded = _run(_call(url, {'X-Participant': 'eng', 'X-Token': 'eng-secret',
                                        'X-Forwarded-For': '127.0.0.1'}, 'artifact_upload', path=proof))
        assert json.loads(forwarded.content[0].text)['error']['code'] == 'unavailable'
        assert call('artifact_upload', token=None, path=proof)['error']['code'] == 'unauthorized'
        assert call('artifact_upload', token='wrong', path=proof)['error']['code'] == 'unauthorized'
        assert call('artifact_upload', participant='arch', path=proof)['error']['code'] == 'unauthorized'
        doc = call('doc_create', doc_type='note', title='HTTP MCP lifecycle', body_md='old text', scope=configured['rig']['epic']['id'])
        assert doc['ok'], doc
        did = doc['value']['id']
        assert call('doc_read', id=did, limit=4)['ok']
        edited = call('doc_edit', id=did, expected_version=1, edits=[{'old_text': 'old', 'new_text': 'new'}])
        assert edited['ok'] and edited['value']['version'] == 2
        assert call('link_create', from_id=configured['rig']['t1']['id'], to_id=did, relation='evidence_for')['ok']
        out = call('artifact_upload', path=proof)
        assert out['ok'], out
        assert out['value']['created_by'] == 'eng' and out['value']['staged']
        aid = out['value']['id']
        sent = call('message_send', ticket_id=configured['rig']['t1']['id'], kind='note', text='attached HTTP proof', artifacts=[aid])
        assert sent['ok'], sent
        assert not call('artifact_read', id=aid)['value']['staged']
        assert call('artifact_upload', path=str(configured['scratch'] / 'seat.txt'))['ok']
        assert call('artifact_upload', path=str(configured['other'] / 'private.txt'))['error']['code'] == 'upload_refused'
        assert call('artifact_upload', path='proof.txt')['error']['code'] == 'upload_refused'
        assert call('artifact_upload', path=str(configured['workspace'] / '..' / 'outside.txt'))['error']['code'] == 'upload_refused'
        assert call('artifact_upload', path=proof + ':secret')['error']['code'] == 'upload_refused'
        (configured['workspace'] / 'executable.exe').write_bytes(b'MZ' + bytes(128))
        assert not call('artifact_upload', path=str(configured['workspace'] / 'executable.exe'))['ok']
        with (configured['workspace'] / 'large.txt').open('wb') as file:
            file.truncate(25 * 1024 * 1024 + 1)
        assert call('artifact_upload', path=str(configured['workspace'] / 'large.txt'))['error']['code'] == 'upload_refused'


def test_denials_do_not_open_requested_files(configured, monkeypatch):
    client = configured['app']
    import edp8.local_upload as local
    def forbidden(*args, **kw):
        pytest.fail('denied request reached file opening')
    monkeypatch.setattr(local, 'workspace_file', forbidden)
    policy = HttpUploadPolicy.from_environment('http://127.0.0.1:1234')
    assert policy.enabled
    good = BoardClient(participant='eng', token='eng-secret', client=client)
    proof = str(configured['workspace'] / 'proof.txt')
    assert HttpUploadPolicy().upload(good, proof, '', '127.0.0.1')['error']['code'] == 'unavailable'
    assert policy.upload(good, proof, '', '192.0.2.10')['error']['code'] == 'unavailable'
    for who, token in [('eng', None), ('eng', 'wrong'), ('missing', 'anything'), ('owner', 'owner-secret')]:
        out = policy.upload(BoardClient(participant=who, token=token, client=client), proof, '', '127.0.0.1')
        assert not out['ok']
    assert not policy.upload(good, str(configured['other'] / 'private.txt'), '', '127.0.0.1')['ok']
    assert not policy.upload(good, 'proof.txt', '', '127.0.0.1')['ok']
    def unreachable():
        from edp8.client import BoardUnreachable
        raise BoardUnreachable('isolated test')
    monkeypatch.setattr(good, 'upload_authorize', unreachable)
    assert policy.upload(good, proof, '', '127.0.0.1')['error']['code'] == 'unavailable'


def test_strict_auth_refuses_header_only_legacy_agent(configured):
    client = configured['app']
    # Existing trusted-mode whoami remains compatible; new file authorization is stricter.
    configured['tokens'].write_text(json.dumps({'owner': 'owner-secret', 'agents': {}}))
    headers = {'X-Participant': 'eng', 'X-Token': 'invented'}
    assert client.get('/v1/whoami', headers=headers).json()['ok']
    assert not client.post('/v1/artifacts/upload-authorize', headers=headers).json()['ok']


@pytest.mark.parametrize('change', ['off', 'remote_board', 'invalid_url', 'public', 'remote_bind', 'missing', 'malformed', 'broad', 'overlap'])
def test_invalid_or_remote_configuration_fails_closed(configured, monkeypatch, change):
    url = 'http://127.0.0.1:1234'
    if change == 'off': monkeypatch.delenv('EDP8_HTTP_UPLOAD_MODE')
    if change == 'remote_board': url = 'https://board.example.com'
    if change == 'invalid_url': url = 'http://[invalid'
    if change == 'public': monkeypatch.setenv('EDP8_PUBLIC_URL', 'https://board.example.com')
    if change == 'remote_bind': monkeypatch.setenv('EDP8_MCP_HOST', '0.0.0.0')
    if change == 'missing': monkeypatch.delenv('EDP8_HTTP_UPLOAD_POLICY')
    if change == 'malformed': configured['config'].write_text('{')
    if change in ('broad', 'overlap'):
        data = configured['data']
        if change == 'broad': data['workspace_root'] = str(Path.home().resolve())
        else: data['seats']['arch']['scratch_root'] = data['seats']['eng']['scratch_root']
        configured['config'].write_text(json.dumps(data))
    assert not HttpUploadPolicy.from_environment(url).enabled


def test_http_policy_root_cannot_be_retargeted(configured):
    client = configured['app']
    if os.name != 'nt': pytest.skip('Windows junction test')
    policy = HttpUploadPolicy.from_environment('http://127.0.0.1:1234')
    root = configured['workspace']
    backup = root.with_name('workspace-original')
    root.rename(backup)
    out = subprocess.run(['cmd', '/c', 'mklink', '/J', str(root), str(configured['other'])], capture_output=True)
    assert out.returncode == 0
    try:
        out = policy.upload(BoardClient(participant='eng', token='eng-secret', client=client), str(root / 'private.txt'), '', '127.0.0.1')
        assert not out['ok'], 'configured canonical root was re-resolved to another seat scratch'
        assert out['error']['code'] == 'upload_refused'
    finally:
        root.rmdir()
        backup.rename(root)


def test_http_junction_escape_refused(configured):
    client = configured['app']
    if os.name != 'nt': pytest.skip('Windows junction test')
    junction = configured['workspace'] / 'escape'
    out = subprocess.run(['cmd', '/c', 'mklink', '/J', str(junction), str(configured['other'])], capture_output=True)
    assert out.returncode == 0
    try:
        policy = HttpUploadPolicy.from_environment('http://127.0.0.1:1234')
        out = policy.upload(BoardClient(participant='eng', token='eng-secret', client=client), str(junction / 'private.txt'), '', '127.0.0.1')
        assert out['error']['code'] == 'upload_refused'
    finally:
        junction.rmdir()
