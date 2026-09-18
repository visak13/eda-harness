"""Workspace boundary and genuine MCP stdio workflow (isolated ports/home only)."""
import asyncio
import json
import os
from pathlib import Path
import sys

import pytest
from test_context_tools import board, client, rig, H
from test_mcp_http import _Server, _free_port
from edp8.client import BoardClient
from edp8.service import create_app


def test_workspace_upload_and_message_parity(client, rig, tmp_path, monkeypatch):
    monkeypatch.setenv('EDP8_HOME', str(tmp_path / 'boardhome'))
    root = tmp_path / 'workspace'
    root.mkdir()
    (root / 'proof.txt').write_text('tool upload proof')
    outside = tmp_path / 'outside.txt'
    outside.write_text('must not upload')
    local = BoardClient(participant='eng', client=client, workspace_root=root)
    assert local.artifact_upload('../outside.txt')['error']['code'] == 'upload_refused'
    assert BoardClient(participant='eng', client=client).artifact_upload(str(outside))['error']['code'] == 'unavailable'
    staged = local.artifact_upload('proof.txt')
    assert staged['ok'], staged
    aid = staged['value']['id']
    assert staged['value']['staged']
    assert not BoardClient(participant='owner', client=client).message_send(rig['t1']['id'], 'note', 'steal', artifacts=[aid])['ok']
    sent = local.message_send(rig['t1']['id'], 'note', 'proof', artifacts=[aid])
    assert sent['ok'], sent
    assert not local.artifact_read(aid)['value']['staged']
    assert client.get(f'/v1/artifacts/{aid}/content', headers=H).content == b'tool upload proof'
    huge = root / 'huge.txt'
    with huge.open('wb') as f:
        f.truncate(25 * 1024 * 1024 + 1)
    assert local.artifact_upload('huge.txt')['error']['code'] == 'upload_refused'


def test_opened_handle_recheck_rejects_escape(tmp_path, monkeypatch):
    from edp8 import local_upload
    root = tmp_path / 'root'; root.mkdir()
    (root / 'ok.txt').write_text('safe')
    monkeypatch.setattr(local_upload, '_handle_path', lambda f: tmp_path / 'escaped')
    with pytest.raises(local_upload.UploadRefused, match='escaped'):
        with local_upload.workspace_file(root, 'ok.txt'):
            pytest.fail('escaped file yielded')


def test_symlink_containment(tmp_path):
    from edp8.local_upload import UploadRefused, workspace_file
    root = tmp_path / 'root'; root.mkdir()
    outside = tmp_path / 'out.txt'; outside.write_text('no')
    try:
        (root / 'link.txt').symlink_to(outside)
    except OSError:
        pytest.skip('host does not grant symlink privilege; opened-handle test remains mandatory')
    with pytest.raises(UploadRefused):
        with workspace_file(root, 'link.txt'):
            pytest.fail('symlink escape yielded')


def test_real_stdio_mcp_lifecycle(board, client, rig, tmp_path, monkeypatch):
    from mcp.client.stdio import stdio_client, StdioServerParameters
    from mcp.client.session import ClientSession
    home = tmp_path / 'home'; home.mkdir()
    root = tmp_path / 'workspace'; root.mkdir()
    (root / 'proof.txt').write_text('actual MCP upload')
    monkeypatch.setenv('EDP8_HOME', str(home))
    port = _free_port()
    env = {**os.environ, 'EDP8_BOARD_URL': f'http://127.0.0.1:{port}',
           'EDP8_PARTICIPANT': 'eng', 'EDP_HANDLE': 'eng', 'EDP8_ROLE': 'engineer',
           'EDP8_UPLOAD_ROOT': str(root), 'EDP8_EMBEDDER': 'none', 'EDP8_HOME': str(home),
           'EDP8_TOKEN': '', 'EDP8_ADMIN_TOKEN': 't'}
    async def workflow():
        async with stdio_client(StdioServerParameters(command=sys.executable, args=['-m', 'edp8.mcp_server', '--stdio'], env=env)) as (r, w):
            async with ClientSession(r, w) as session:
                await session.initialize()
                names = {t.name for t in (await session.list_tools()).tools}
                assert {'doc_edit', 'context_delta', 'describe_objects', 'artifact_upload'} <= names
                async def call(name, **args):
                    response = await session.call_tool(name, args)
                    result = json.loads(response.content[0].text)
                    assert result['ok'], result
                    return result['value']
                doc = await call('doc_create', doc_type='note', title='MCP proof', body_md='old text', scope=rig['epic']['id'])
                await call('doc_read', id=doc['id'], limit=4)
                edited = await call('doc_edit', id=doc['id'], expected_version=1, edits=[{'old_text': 'old', 'new_text': 'new'}])
                assert edited['version'] == 2
                await call('link_create', from_id=rig['t1']['id'], to_id=doc['id'], relation='evidence_for')
                art = await call('artifact_upload', path='proof.txt')
                await call('message_send', ticket_id=rig['t1']['id'], kind='note', text='attached', artifacts=[art['id']])
                assert not (await call('artifact_read', id=art['id']))['staged']
                full = await call('context')
                assert not (await call('context_delta', cursor=full['cursor']))['changed']
    with _Server(create_app(board, admin_token='t'), port):
        asyncio.run(workflow())


def test_real_pi_local_adapter(board, client, rig, tmp_path, monkeypatch):
    import subprocess
    home = tmp_path / 'home'; home.mkdir()
    root = tmp_path / 'workspace'; root.mkdir()
    (root / 'proof.txt').write_text('Pi proof')
    (tmp_path / 'outside.txt').write_text('must remain outside')
    monkeypatch.setenv('EDP8_HOME', str(home))
    port = _free_port()
    env = {**os.environ, 'EDP8_BOARD_URL': f'http://127.0.0.1:{port}',
           'EDP8_PARTICIPANT': 'eng', 'EDP_HANDLE': 'eng', 'EDP8_TOKEN': '',
           'S7_WORKSPACE': str(root), 'EDP_PI_TASKS_DIR': str(home), 'EDP8_LANE_DIR': str(home)}
    with _Server(create_app(board, admin_token='t'), port):
        proc = subprocess.run(['node', '--experimental-strip-types', 'tests/pi_ext/s7_upload.ts'],
                              env=env, capture_output=True, text=True, timeout=40)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    result = json.loads(proc.stdout)
    assert result['ok'] and board._get('artifact', result['artifact'], 'artifact').created_by == 'eng'


def test_windows_junction_containment(tmp_path):
    if os.name != 'nt':
        pytest.skip('Windows junction test')
    import subprocess
    from edp8.local_upload import UploadRefused, workspace_file
    root = tmp_path / 'root'; root.mkdir()
    outside = tmp_path / 'outside'; outside.mkdir()
    (outside / 'no.txt').write_text('no')
    junction = root / 'junction'
    result = subprocess.run(['cmd', '/c', 'mklink', '/J', str(junction), str(outside)], capture_output=True)
    assert result.returncode == 0
    try:
        with pytest.raises(UploadRefused):
            with workspace_file(root, 'junction/no.txt'):
                pytest.fail('junction escaped')
    finally:
        junction.rmdir()

