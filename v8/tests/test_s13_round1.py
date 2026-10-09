"""S13 round-1 regressions (t-dac2a14caf): the adversary's probes from report-b020cd0eca (evidence commit 9f907d14),
moved into the default suite. Each failed on main@bfbef15d and passes with its fix; the three negative controls
(legacy guest read, SSE foreign evidence_ref, loopback guest boundary) pass on both. All tokens are synthetic
canaries; every board and process boundary is private."""
import asyncio
import json

from test_e0cec_s5_guest import (rig, _post, _upload, _feed, _frames, _data,
                               OWNER, ARCH, GUEST, GINA_T, ADMIN)


def test_guest_settles_owner_ask(rig):
    c, a, b = rig['c'], rig['A'], rig['board']
    ask = _post(c, '/v1/messages', {'ticket_id': a['story'], 'kind': 'question', 'to': 'owner',
                                  'text': 'Owner must pick the rollout timing'}, ARCH)
    assert b._settled(ask['id']) is None
    _post(c, '/v1/messages', {'ticket_id': a['story'], 'kind': 'note', 'reply_to': ask['id'],
                            'text': 'I am a guest and cannot decide this'}, GUEST)
    assert b._settled(ask['id']) is None, 'guest note cleared an owner-addressed ask'


def test_codex_no_effort_cap(tmp_path, monkeypatch):
    from edp_pool.codex_launcher import CodexSpawner
    from edp_pool import codex_launcher
    from edp_pool.service import PoolService
    (tmp_path / 'models.json').write_text(json.dumps({'models': {
        'review-model': {'harness': 'codex', 'provider': 'codex', 'model': 'gpt-6-astra', 'effort_cap': 'low'}},
        'role_models': {'adversary': ['review-model']}}))
    captured = {}
    class FakeProc:
        pid = 9999999
        def poll(self): return None
    def launch(argv, **kw):
        captured.update(kw['env'])
        return FakeProc()
    monkeypatch.setattr(codex_launcher.subprocess, 'Popen', launch)
    sp = CodexSpawner(agent_home=str(tmp_path))
    svc = PoolService(sp, state_path=tmp_path / 'pool-state.json')
    env = svc._clamp_seat_effort('adversary', 'adversary.synthetic', 'review-model', {'EDP_CODEX_EFFORT': 'high'})
    sp.launch('s13-synthetic', 'adversary', 'adversary.synthetic', model='review-model', mode='headless', extra_env=env)
    assert captured.get('EDP_CODEX_EFFORT') == 'low', 'no EDP_SEAT_EFFORT bypasses low cap through EDP_CODEX_EFFORT'


def test_legacy_guest_read(rig):
    c, b = rig['c'], rig['B']
    r = c.get(f"/ui/ticket/{b['story']}", params={'as': 'gina', 'token': GINA_T})
    assert r.status_code == 403, f"legacy: HTTP {r.status_code}; foreign title present={'zebra story' in r.text}"


def test_idempotency_revocation(rig):
    c, a = rig['c'], rig['A']
    h = {**GUEST, 'Idempotency-Key': 's13-revoke'}
    body = {'ticket_id': a['story'], 'kind': 'note', 'text': 'guest request before removal'}
    assert c.post('/v1/messages', headers=h, json=body).status_code == 200
    _post(c, f"/v1/epics/{a['epic']}/members", {'members': []}, OWNER, method='PUT')
    assert c.get(f"/v1/tickets/{a['story']}", headers=GUEST).status_code == 404
    r = c.post('/v1/messages', headers=h, json=body)
    assert r.status_code in (401, 403, 404), f"replay after revoke: HTTP {r.status_code}; cached row={r.json().get('value',{}).get('replay')}"


def test_secret_filename_header(rig):
    c, a = rig['c'], rig['A']
    _post(c, f"/v1/epics/{a['epic']}/members", {'members': []}, OWNER, method='PUT')
    fake_key = 'ghp_' + 'S13Canary' * 5
    art = _upload(c, ARCH, data=b'harmless notes', name=f'{fake_key}.txt', ctype='text/plain')
    _post(c, '/v1/artifacts/finalize', {'artifact_ids': [art], 'ticket_id': a['story']}, ARCH)
    _post(c, f"/v1/epics/{a['epic']}/members", {'members': ['gina']}, OWNER, method='PUT')
    meta = c.get(f'/v1/artifacts/{art}', headers=GUEST)
    assert fake_key not in meta.text
    r = c.get(f'/v1/artifacts/{art}/content', headers=GUEST)
    leaked = fake_key in str(r.headers)
    assert not leaked, 'secret filename withheld in JSON but leaked in Content-Disposition'


def test_sse_foreign_evidence_ref(rig):
    c, board, a, b = rig['c'], rig['board'], rig['A'], rig['B']
    _post(c, f"/v1/criteria/{a['crit']}", {'evidence_ref': b['design']}, OWNER, method='PATCH')
    rest = c.get('/v1/events', params={'since': 0, 'watch': True}, headers=GUEST)
    assert b['design'] not in rest.text
    async def read():
        response = await _feed(c)(since=0, watch=True, a=board.participant('gina'))
        frames = _data(await _frames(response, stop_after_ready=True))
        await response.body_iterator.aclose()
        return frames
    frames = asyncio.run(read())
    assert b['design'] not in json.dumps(frames), 'SSE exposes nonmember evidence_ref redacted by REST'


def test_idempotency_credential_revocation(rig, monkeypatch, tmp_path):
    c, a = rig['c'], rig['A']
    h = {**GUEST, 'Idempotency-Key': 's13-token-revoke'}
    body = {'ticket_id': a['story'], 'kind': 'note', 'text': 'guest before token rotation'}
    assert c.post('/v1/messages', headers=h, json=body).status_code == 200
    tokens = tmp_path / 'tokens.json'
    tokens.write_text(json.dumps({'gina': 'new-synthetic-token', 'agents': {}}))
    import os, time
    os.utime(tokens, (time.time() + 5, time.time() + 5))
    assert c.get(f"/v1/tickets/{a['story']}", headers=GUEST).status_code == 401
    r = c.post('/v1/messages', headers=h, json=body)
    assert r.status_code == 401, f'revoked credential replay: HTTP {r.status_code}'


def test_updater_staged_msi_tamper(tmp_path, monkeypatch):
    """Exercise the real helper; fake process/MSI boundaries never install anything."""
    from edp8 import updater, update_helper as helper
    import hashlib
    original, changed = b'original installer', b'tampered installer'
    monkeypatch.setattr(updater.settings, 'data_dir', lambda: tmp_path)
    monkeypatch.setattr(updater, '_read', lambda src: original)
    name = 'Heronry Desktop-0.9.2.msi'
    rel = updater.Release('0.9.2', {name: 'synthetic'}, {name: hashlib.sha256(original).hexdigest()})
    target = updater.download(rel)['msi']
    target.write_bytes(changed)
    reached = []
    monkeypatch.setattr(helper, '_park', lambda p: [])
    monkeypatch.setattr(helper, '_run', lambda *a, **kw: True)
    monkeypatch.setattr(helper, '_close_app', lambda p: None)
    monkeypatch.setattr(helper, 'holders', lambda *a, **kw: [])
    monkeypatch.setattr(helper, '_log', lambda *a: None)
    monkeypatch.setattr(helper, '_installed', lambda p: '0.9.2')
    monkeypatch.setattr(helper, '_health_version', lambda url: '0.9.2')
    monkeypatch.setattr(helper, '_resume', lambda *a: [])
    monkeypatch.setattr(helper, '_msiexec', lambda p, step, args, log: reached.append(target.read_bytes() == changed) or 0)
    plan = {'from_version': '0.9.1', 'to_version': '0.9.2', 'msi': str(target), 'install_dir': str(tmp_path),
            'stop_argv': [], 'start_argv': [], 'health_url': 'http://127.0.0.1:1', 'upgrade_code': 'synthetic'}
    result = {}
    helper._msi_steps(plan, lambda state, reason='', **kw: result.update(state=state) or 0)
    assert not any(reached), f'tampered verified-cache MSI reached installer; outcome={result}'


def test_updater_helper_exception_recovery(tmp_path, monkeypatch):
    from edp8 import update_helper as helper
    plan = {'from_version': '0.9.1', 'to_version': '0.9.2', 'result': str(tmp_path / 'result.json'),
            'kind': 'msi', 'caller_pid': 0, 'stop_argv': ['private-stop'], 'start_argv': ['private-start'],
            'install_dir': str(tmp_path), 'health_url': 'http://127.0.0.1:1', 'log': str(tmp_path / 'update.log')}
    path = tmp_path / 'plan.json'
    path.write_text(json.dumps(plan))
    actions = []
    monkeypatch.setattr(helper, '_pid_alive', lambda pid: False)
    monkeypatch.setattr(helper, '_park', lambda p: actions.append('park') or ['synthetic-seat'])
    def run(p, step, *a, **kw):
        actions.append(step)
        if step == 'stop':
            from pathlib import Path
            log = Path(p['log'])
            log.unlink()  # only this tmp_path fixture's log; no recursive file operations
            log.mkdir()  # make the real next log write fail after the stop boundary
        return True
    monkeypatch.setattr(helper, '_run', run)
    monkeypatch.setattr(helper, '_close_app', lambda p: None)
    monkeypatch.setattr(helper, 'holders', lambda *a, **kw: [])
    monkeypatch.setattr(helper, '_post_event', lambda *a: None)
    monkeypatch.setattr(helper, '_health_version', lambda url: '0.9.1')  # the restarted old board answers
    monkeypatch.setattr(helper, '_resume', lambda p, handles: actions.append(('resume', handles)) or handles)
    assert helper.main(str(path)) == 1  # not "ok": the update did not happen, the old install came back
    assert 'stop' in actions
    assert 'start' in actions or 'start previous' in actions, f'real log I/O failure leaves stopped install and parked seats: {actions}'
    assert ('resume', ['synthetic-seat']) in actions
    res = json.loads((tmp_path / 'result.json').read_text())
    assert res['state'] == 'rolled_back' and 'KeyError' in res['error'] and res['resumed'] == ['synthetic-seat']


def test_f2_recovery_failure_keeps_both_errors(tmp_path, monkeypatch):
    """F2: when the restart itself raises, the receipt says failed and names the original and the recovery error."""
    from edp8 import update_helper as helper
    plan = {'from_version': '0.9.1', 'to_version': '0.9.2', 'result': str(tmp_path / 'result.json'),
            'kind': 'msi', 'caller_pid': 0, 'stop_argv': ['private-stop'], 'start_argv': ['private-start'],
            'install_dir': str(tmp_path), 'health_url': 'http://127.0.0.1:1', 'log': str(tmp_path / 'update.log')}
    path = tmp_path / 'plan.json'
    path.write_text(json.dumps(plan))
    monkeypatch.setattr(helper, '_pid_alive', lambda pid: False)
    monkeypatch.setattr(helper, '_park', lambda p: ['synthetic-seat'])
    def run(p, step, *a, **kw):
        if step == 'start':
            raise OSError('start refused')
        return True
    monkeypatch.setattr(helper, '_run', run)
    monkeypatch.setattr(helper, '_close_app', lambda p: None)
    monkeypatch.setattr(helper, 'holders', lambda *a, **kw: [])
    monkeypatch.setattr(helper, '_post_event', lambda *a: None)
    assert helper.main(str(path)) == 1
    res = json.loads((tmp_path / 'result.json').read_text())
    assert res['state'] == 'failed' and 'KeyError' in res['error'] and 'start refused' in res['recovery_error']


def test_exact_id_find(rig):
    c, a = rig['c'], rig['A']
    failures = []
    for kind, target in [('ticket', a['story']), ('doc', a['design']), ('message', a['msg'])]:
        _post(c, '/v1/messages', {'ticket_id': a['story'], 'kind': 'note', 'text': f'Citation mentions {target}'}, ARCH)
        r = c.get('/v1/find', params={'q': target, 'k': 10}, headers=OWNER)
        assert r.status_code == 200
        ids = [h['id'] for h in r.json()['value']]
        if not ids or ids[0] != target:
            failures.append({'kind': kind, 'target_returned': target in ids, 'hits': len(ids)})
    assert not failures, f'exact object IDs do not rank first: {failures}'


def test_exact_title_find(rig):
    c, a = rig['c'], rig['A']
    title = 'S13 Calibration Rulebook'
    doc = _post(c, '/v1/docs', {'doc_type': 'note', 'scope': a['epic'], 'title': title,
                               'body_md': 'orientation ' * 1000}, ARCH)
    _post(c, '/v1/messages', {'ticket_id': a['story'], 'kind': 'note', 'text': title}, ARCH)
    hits = c.get('/v1/find', params={'q': title, 'k': 10}, headers=OWNER).json()['value']
    rank = next((i+1 for i,h in enumerate(hits) if h['id']==doc['id']), None)
    assert rank == 1, f'exact title target ranked {rank}'


def test_private_loopback_guest_boundary(rig):
    """Real wire smoke: only this private in-memory app, on an OS-assigned spare port."""
    import socket, threading, time
    import httpx, uvicorn
    sock = socket.socket()
    sock.bind(('127.0.0.1', 0))
    server = uvicorn.Server(uvicorn.Config(rig['c'].app, log_level='critical', lifespan='off'))
    worker = threading.Thread(target=server.run, kwargs={'sockets': [sock]}, daemon=True)
    worker.start()
    try:
        for _ in range(100):
            if server.started: break
            time.sleep(.05)
        assert server.started
        with httpx.Client(base_url=f'http://127.0.0.1:{sock.getsockname()[1]}') as c:
            assert c.get(f"/v1/tickets/{rig['A']['story']}", headers=GUEST).status_code==200
            assert c.get(f"/v1/tickets/{rig['B']['story']}", headers=GUEST).status_code==404
            assert c.post('/v1/sessions/spawn', json={}, headers=GUEST).status_code==403
    finally:
        server.should_exit = True
        worker.join(timeout=5)
        sock.close()


def test_f1_guest_download_is_named_by_the_artifact_on_every_branch(rig):
    """F1: ordinary text, withheld text and binary downloads all carry the neutral name for a guest; the owner
    keeps the uploader's filename."""
    c, a = rig['c'], rig['A']
    _post(c, f"/v1/epics/{a['epic']}/members", {'members': []}, OWNER, method='PUT')  # shared after the upload
    fake_key = 'ghp_' + 'S13Canary' * 5
    arts = {'text': _upload(c, ARCH, data=b'harmless notes', name=f'{fake_key}.txt', ctype='text/plain'),
            'withheld': _upload(c, ARCH, data=f'token {fake_key}'.encode(), name=f'{fake_key}-w.txt',
                                ctype='text/plain'),
            'binary': _upload(c, ARCH, name=f'{fake_key}.png')}
    _post(c, '/v1/artifacts/finalize', {'artifact_ids': list(arts.values()), 'ticket_id': a['story']}, ARCH)
    _post(c, f"/v1/epics/{a['epic']}/members", {'members': ['gina']}, OWNER, method='PUT')
    for branch, art in arts.items():
        disp = c.get(f'/v1/artifacts/{art}/content', headers=GUEST).headers['content-disposition']
        assert fake_key not in disp and art in disp, (branch, disp)
        assert fake_key in c.get(f'/v1/artifacts/{art}/content', headers=OWNER).headers['content-disposition']


def test_f3_a_member_guest_still_gets_its_replay(rig):
    """F3: re-authorising a replay keeps idempotency for a caller who is still allowed."""
    c, a = rig['c'], rig['A']
    h = {**GUEST, 'Idempotency-Key': 's13-still-member'}
    body = {'ticket_id': a['story'], 'kind': 'note', 'text': 'guest retry'}
    first = c.post('/v1/messages', headers=h, json=body).json()['value']
    again = c.post('/v1/messages', headers=h, json=body).json()['value']
    assert again['id'] == first['id'] and again['replay'] is True


def _low_cap_catalog(tmp_path, harness, model):
    (tmp_path / 'models.json').write_text(json.dumps({'models': {
        'review-model': {'harness': harness, 'provider': harness if harness == 'codex' else 'openai', 'model': model,
                         'effort_cap': 'low'}},
        'role_models': {'adversary': ['review-model']}}))


def _capture_popen(monkeypatch, module):
    captured = {}

    class FakeProc:
        pid = 9999999
        def poll(self): return None
    monkeypatch.setattr(module.subprocess, 'Popen', lambda argv, **kw: captured.update(kw['env']) or FakeProc())
    return captured


def test_f4_codex_resume_and_a_pass_through_effort_are_capped(tmp_path, monkeypatch):
    """F4: the launcher clamps after every source of effort, on resume too: a process-env EDP_CODEX_EFFORT and an
    extra_env one that never went through the pool's clamp."""
    from edp_pool import codex_launcher
    _low_cap_catalog(tmp_path, 'codex', 'gpt-6-astra')
    captured = _capture_popen(monkeypatch, codex_launcher)
    monkeypatch.setenv('EDP_CODEX_EFFORT', 'high')
    sp = codex_launcher.CodexSpawner(agent_home=str(tmp_path))
    sp.launch('s13-a', 'adversary', 'adversary.synthetic', model='review-model', mode='headless',
              resume_session='synthetic-thread')
    assert captured['EDP_CODEX_EFFORT'] == 'low'
    monkeypatch.delenv('EDP_CODEX_EFFORT')
    sp.launch('s13-b', 'adversary', 'adversary.synthetic', model='review-model', mode='headless',
              extra_env={'EDP_CODEX_EFFORT': 'xhigh', 'EDP_SEAT_EFFORT': 'high'})
    assert captured['EDP_CODEX_EFFORT'] == 'low' and captured['EDP_SEAT_EFFORT'] == 'low'


def test_f4_pi_thinking_is_capped(tmp_path, monkeypatch):
    from edp_pool import pi_launcher
    _low_cap_catalog(tmp_path, 'pi', 'openai/gpt-6-astra')
    captured = _capture_popen(monkeypatch, pi_launcher)
    sp = pi_launcher.PiSpawner(agent_home=str(tmp_path))
    sp.launch('s13-p', 'adversary', 'adversary.synthetic', model='review-model', mode='headless',
              extra_env={'EDP_PI_THINKING': 'high'})
    assert captured['EDP_PI_THINKING'] == 'low'


def test_f4_pool_clamp_records_capped_harness_effort(tmp_path):
    from edp_pool.codex_launcher import CodexSpawner
    from edp_pool.service import PoolService
    _low_cap_catalog(tmp_path, 'codex', 'gpt-6-astra')
    svc = PoolService(CodexSpawner(agent_home=str(tmp_path)), state_path=tmp_path / 'pool-state.json')
    env = svc._clamp_seat_effort('adversary', 'adversary.synthetic', 'review-model',
                                 {'EDP_CODEX_EFFORT': 'high', 'EDP_PI_THINKING': 'medium', 'X': '1'})
    assert env == {'EDP_CODEX_EFFORT': 'low', 'EDP_PI_THINKING': 'low', 'X': '1'}


def test_f5_exact_hits_keep_the_guest_type_and_epic_filters(rig):
    """F5: precedence never widens a search: a guest's exact query for another epic's ticket finds nothing of it,
    a types filter drops an exact id of another type, and an epic filter drops an exact id outside it."""
    c, a, b = rig['c'], rig['A'], rig['B']
    guest_ids = [h['id'] for h in c.get('/v1/find', params={'q': b['story'], 'k': 10}, headers=GUEST).json()['value']]
    assert b['story'] not in guest_ids
    typed = c.get('/v1/find', params={'q': a['story'], 'k': 10, 'types': 'doc'}, headers=OWNER).json()['value']
    assert a['story'] not in [h['id'] for h in typed]
    other = c.get('/v1/find', params={'q': b['story'], 'k': 10, 'epic_id': a['epic']}, headers=OWNER).json()['value']
    assert b['story'] not in [h['id'] for h in other]
    hits = c.get('/v1/find', params={'q': a['story'], 'k': 10}, headers=GUEST).json()['value']
    assert hits[0]['id'] == a['story'] and hits[0]['epic_id'] == a['epic']


def _msi_plan(tmp_path):
    import hashlib
    plan = {'from_version': '0.9.1', 'to_version': '0.9.2', 'install_dir': str(tmp_path), 'upgrade_code': 'synthetic',
            'stop_argv': ['stop'], 'start_argv': ['start'], 'health_url': 'http://127.0.0.1:1',
            'log': str(tmp_path / 'update.log')}
    for key, name in (('msi', 'new.msi'), ('previous_msi', 'old.msi')):
        f = tmp_path / name
        f.write_bytes(name.encode())
        plan[key], plan[f'{key}_sha256'] = str(f), hashlib.sha256(f.read_bytes()).hexdigest()
    return plan


def _msi_boundaries(monkeypatch, helper, actions, park=lambda p: []):
    monkeypatch.setattr(helper, '_park', lambda p: actions.append('park') or park(p))
    monkeypatch.setattr(helper, '_run', lambda p, step, *a, **kw: actions.append(step) or True)
    monkeypatch.setattr(helper, '_close_app', lambda p: None)
    monkeypatch.setattr(helper, 'holders', lambda *a, **kw: [])
    monkeypatch.setattr(helper, '_installed', lambda p: '0.9.1')
    monkeypatch.setattr(helper, '_health_version', lambda url: '0.9.1')
    monkeypatch.setattr(helper, '_resume', lambda *a: [])
    monkeypatch.setattr(helper, '_wait_msi_idle', lambda p: None)
    monkeypatch.setattr(helper, '_msiexec', lambda p, step, args, log: actions.append(('msiexec', step)) or 0)


def test_f6_a_changed_previous_msi_fails_before_anything_stops(tmp_path, monkeypatch):
    from edp8 import update_helper as helper
    plan, actions, result = _msi_plan(tmp_path), [], {}
    (tmp_path / 'old.msi').write_bytes(b'changed')
    _msi_boundaries(monkeypatch, helper, actions)
    helper._msi_steps(plan, lambda state, reason='', **kw: result.update(state=state, reason=reason) or 1)
    assert actions == [] and result['state'] == 'failed' and 'old.msi changed' in result['reason']


def test_f6_a_change_after_the_first_check_never_reaches_msiexec(tmp_path, monkeypatch):
    """F6: the digest is checked again at the last moment; a change during the stop restarts the old version."""
    from edp8 import update_helper as helper
    plan, actions, result = _msi_plan(tmp_path), [], {}
    _msi_boundaries(monkeypatch, helper, actions, park=lambda p: (tmp_path / 'new.msi').write_bytes(b'x') and [])
    helper._msi_steps(plan, lambda state, reason='', **kw: result.update(state=state, reason=reason) or 1)
    assert not [a for a in actions if isinstance(a, tuple)], actions
    assert 'stop' in actions and 'start' in actions and result['state'] == 'rolled_back'
    assert 'new.msi changed' in result['reason']


def test_f7_a_guest_settles_only_what_was_asked_of_it(rig):
    """F7 ruling: a guest's resolves= never settles another participant's ask; an ask put to the guest is answered
    by the guest's reply."""
    c, a, b = rig['c'], rig['A'], rig['board']
    to_owner = _post(c, '/v1/messages', {'ticket_id': a['story'], 'kind': 'question', 'to': 'owner',
                                       'text': 'Owner picks the date'}, ARCH)
    _post(c, '/v1/messages', {'ticket_id': a['story'], 'kind': 'note', 'text': 'noted', 'resolves': [to_owner['id']]},
          GUEST)
    assert b._settled(to_owner['id']) is None
    to_guest = _post(c, '/v1/messages', {'ticket_id': a['story'], 'kind': 'question', 'to': 'gina',
                                       'text': 'Which browser do you use?'}, ARCH)
    _post(c, '/v1/messages', {'ticket_id': a['story'], 'kind': 'note', 'reply_to': to_guest['id'], 'text': 'Firefox'},
          GUEST)
    assert b.ask_resolved(b.store.get('message', to_guest['id']))


def test_f3_residual_doc_scope_revoked_while_ticket_stays_readable(rig):
    """S13 F3 residual (adversary m-fea8e76214, architect m-10b64902e7): the replay re-scope covers every id the
    request names, not just ticket_id: a doc comment cached before the doc left the guest's epic no longer replays."""
    c, a, board = rig['c'], rig['A'], rig['board']
    body = {'ticket_id': a['story'], 'design_ref': a['note'], 'reviewed_version': 1,
            'text': 'Synthetic doc comment', 'idempotency_key': 's13-doc-scope'}
    headers = {**GUEST, 'Idempotency-Key': 's13-doc-scope-http'}
    first = c.post('/v1/docs/comments', json=body, headers=headers)
    assert first.status_code == 200 and first.json()['ok'], first.json()
    assert c.post('/v1/docs/comments', json=body, headers=headers).status_code == 200  # in scope: replays
    link = next(x for x in board.store.query('link', {'from_id': a['story']}) if x.to_id == a['note'])
    assert c.delete(f'/v1/links/{link.id}', headers=OWNER).status_code == 200
    assert c.get(f"/v1/tickets/{a['story']}", headers=GUEST).status_code == 200
    assert c.get(f"/v1/docs/{a['note']}", headers=GUEST).status_code == 404
    fresh = c.post('/v1/docs/comments', json={**body, 'idempotency_key': 's13-doc-new'}, headers=GUEST)
    assert fresh.status_code == 404, fresh.json()
    replay = c.post('/v1/docs/comments', json=body, headers=headers)
    assert replay.status_code == 404, replay.json()
