"""S18 round-1 regressions (t-fb9350ba64): the adversary's hostile probes from report-8c32953372 (commit 8b3482da),
moved into the default suite, plus the repair contracts' extra paths. Synthetic boards and data; process calls are
fakes."""
import sys
import html
import json

import pytest

from test_e0cec_s5_guest import rig, _post, OWNER, ARCH, GUEST
from test_s17_summary_first import http, _doc, _call


# the MSI / Win32 update path (msiexec, ctypes.windll): Windows-only code, so Windows-only tests
WINDOWS_ONLY = pytest.mark.skipif(sys.platform != "win32", reason="Windows-only (MSI / Win32 API)")


@pytest.mark.parametrize('canary', ['S18CanaryPlainText98765', 'S18Canary<red>&blue!'])
def test_guest_html_preserves_live_secret_screen(rig, tmp_path, monkeypatch, canary):
    c, a = rig['c'], rig['A']
    _post(c, f"/v1/epics/{a['epic']}/members", {'members': []}, OWNER, method='PUT')
    did = _post(c, '/v1/docs', {'doc_type': 'note', 'title': 'Synthetic secret',
                'body_md': 'Example: `' + canary + '`', 'scope': a['epic']}, ARCH)['id']
    env = tmp_path / '.env'
    env.write_text('APP_SECRET=' + canary, encoding='utf-8')
    monkeypatch.chdir(tmp_path)
    _post(c, f"/v1/epics/{a['epic']}/members", {'members': ['gina']}, OWNER, method='PUT')
    raw = c.get(f'/v1/docs/{did}', headers=GUEST)
    assert raw.status_code == 200 and canary not in raw.text and 'withheld' in raw.text
    rendered = c.get(f'/v1/docs/{did}/html', headers=GUEST)
    assert rendered.status_code == 200
    leaked = canary in html.unescape(rendered.json()['value']['html'])
    assert not leaked, 'known live secret is withheld in raw doc but readable through rendered HTML'


def test_msi_stop_failure_does_not_reach_installer(tmp_path, monkeypatch):
    from edp8 import update_helper as h
    from test_update_s10 import _staged_msis
    actions = []
    plan = {'kind': 'msi', 'from_version': '0.9.1', 'to_version': '0.9.2', **_staged_msis(tmp_path),
            'install_dir': str(tmp_path), 'upgrade_code': 'synthetic', 'stop_argv': ['synthetic-stop'],
            'start_argv': ['synthetic-start'], 'health_url': 'http://127.0.0.1:1', 'log': str(tmp_path/'helper.log')}
    monkeypatch.setattr(h, '_park', lambda p: [])
    monkeypatch.setattr(h, '_run', lambda p, what, *a, **k: actions.append(what) or what != 'stop')
    monkeypatch.setattr(h, '_close_app', lambda p: None)
    monkeypatch.setattr(h, 'holders', lambda *a, **k: [])
    monkeypatch.setattr(h, '_installed', lambda p: '0.9.2')
    monkeypatch.setattr(h, '_health_version', lambda *a, **k: '0.9.2')  # the board still answers
    monkeypatch.setattr(h, '_resume', lambda *a: [])
    monkeypatch.setattr(h, '_msiexec', lambda *a: actions.append('msiexec') or 0)
    result = {}
    h._msi_steps(plan, lambda state, reason='', **k: result.update(state=state, reason=reason, **k) or 0)
    assert 'msiexec' not in actions, f"stop=False ignored: {actions}; outcome={result['state']}"
    # the explicit refusal, not the exception-recovery path (adversary m-096b743260)
    assert result['state'] == 'failed' and 'services did not stop' in result['reason'] and 'error' not in result


@WINDOWS_ONLY
@pytest.mark.parametrize('failure', ['park', 'resume', 'none'])
def test_msi_seat_coordination_failures_are_not_success(tmp_path, monkeypatch, failure):
    from edp8 import update_helper as h
    from test_update_s10 import _staged_msis
    actions = []
    plan = {'kind': 'msi', 'from_version': '0.9.1', 'to_version': '0.9.2', **_staged_msis(tmp_path),
            'install_dir': str(tmp_path), 'upgrade_code': 'synthetic', 'stop_argv': ['synthetic-stop'],
            'start_argv': ['synthetic-start'], 'health_url': 'http://127.0.0.1:1',
            'pool_url': 'http://127.0.0.1:1', 'log': str(tmp_path/'helper.log')}
    def http(url, method='GET', **kw):
        if url.endswith('/v1/sessions'):
            return [{'handle': 'synthetic-seat', 'state': 'active'}]
        if '/v1/park/' in url:
            actions.append('park')
            if failure == 'park':
                raise OSError('synthetic park refusal')
            return {'ok': True}
        if url.endswith('/v1/pool/capabilities'):
            return {}
        if '/v1/resume/' in url:
            actions.append('resume')
            if failure == 'resume':
                raise OSError('synthetic resume refusal')
            return {'ok': True}
        raise AssertionError('unexpected private endpoint')
    monkeypatch.setattr(h, '_http', http)
    monkeypatch.setattr(h, '_run', lambda p, what, *a, **k: actions.append(what) or True)
    monkeypatch.setattr(h, '_close_app', lambda p: None)
    monkeypatch.setattr(h, 'holders', lambda *a, **k: [])
    monkeypatch.setattr(h, '_installed', lambda p: '0.9.2')
    monkeypatch.setattr(h, '_health_version', lambda *a, **k: '0.9.2')
    monkeypatch.setattr(h, '_msiexec', lambda *a: actions.append('msiexec') or 0)
    result = {}
    h._msi_steps(plan, lambda state, reason='', **kw: result.update(state=state, reason=reason, **kw) or 0)
    if failure == 'none':
        assert result['state'] == 'ok' and result['parked'] == result['resumed'] == ['synthetic-seat']
    elif failure == 'park':
        assert 'msiexec' not in actions, f"known active seat failed to park yet installer ran; state={result['state']}, parked={result['parked']}"
    else:
        assert result['state'] != 'ok', f"resume failed but outcome is ok; parked={result['parked']}, resumed={result['resumed']}"


@pytest.mark.parametrize('where', ['heading', 'fence', 'title'])
def test_s18_1_guest_html_screens_every_source_path_and_old_versions(rig, tmp_path, monkeypatch, where):
    """S18-1: the guest HTML view screens the source (raw markdown, inline code, a fenced block, the title, a
    historical version) before rendering; nothing is shown unescaped. An owner still reads the whole doc."""
    c, a = rig['c'], rig['A']
    canary = 'S18Canary<b>&"x"!'
    _post(c, f"/v1/epics/{a['epic']}/members", {'members': []}, OWNER, method='PUT')
    body = {'heading': f'# {canary}\n', 'fence': f'```\n{canary}\n```\n', 'title': 'plain words\n'}[where]
    title = canary if where == 'title' else 'Synthetic secret'
    did = _post(c, '/v1/docs', {'doc_type': 'note', 'title': title, 'body_md': body, 'scope': a['epic']}, ARCH)['id']
    _post(c, f'/v1/docs/{did}', {'body_md': 'clean v2\n', 'title': 'clean'}, ARCH, method='PATCH')  # v1 is history
    (tmp_path / '.env').write_text('APP_SECRET=' + canary, encoding='utf-8')
    monkeypatch.chdir(tmp_path)
    _post(c, f"/v1/epics/{a['epic']}/members", {'members': ['gina']}, OWNER, method='PUT')
    for params in ({}, {'version': 1}):
        r = c.get(f'/v1/docs/{did}/html', params=params, headers=GUEST)
        assert r.status_code == 200
        v = r.json()['value']
        assert canary not in html.unescape(json.dumps(v)) and canary not in r.text
        assert '<b>' not in v['html']
    owner = c.get(f'/v1/docs/{did}/html', params={'version': 1}, headers=OWNER).json()['value']
    assert canary in html.unescape(owner['html'] + owner['title'])


@WINDOWS_ONLY
def test_s18_2_resume_failure_after_install_is_incomplete_and_names_the_seats(tmp_path, monkeypatch):
    """S18-2: the install stays, the outcome is `incomplete` (never ok) and names the seats that did not resume."""
    from edp8 import update_helper as h, updater
    from test_update_s10 import _staged_msis
    plan = {'kind': 'msi', 'from_version': '0.9.1', 'to_version': '0.9.2', **_staged_msis(tmp_path),
            'install_dir': str(tmp_path), 'upgrade_code': 'synthetic', 'stop_argv': ['s'], 'start_argv': ['s'],
            'health_url': 'http://127.0.0.1:1', 'log': str(tmp_path / 'helper.log')}
    monkeypatch.setattr(h, '_park', lambda p: ['seat-a', 'seat-b'])
    monkeypatch.setattr(h, '_resume', lambda p, hs: ['seat-a'])
    monkeypatch.setattr(h, '_run', lambda *a, **k: True)
    monkeypatch.setattr(h, '_close_app', lambda p: None)
    monkeypatch.setattr(h, 'holders', lambda *a, **k: [])
    monkeypatch.setattr(h, '_installed', lambda p: '0.9.2')
    monkeypatch.setattr(h, '_health_version', lambda *a, **k: '0.9.2')
    monkeypatch.setattr(h, '_msiexec', lambda *a: 0)
    out = {}
    h._msi_steps(plan, lambda state, reason='', **kw: out.update(state=state, reason=reason, **kw) or 0)
    assert out['state'] == 'incomplete' and out['resume_failed'] == ['seat-b'] and out['installed'] == '0.9.2'
    assert 'seat-b' in updater.result_text(out) and not updater.result_text(out).startswith('Updated to')


@WINDOWS_ONLY
def test_s18_2_stop_failure_with_services_down_still_installs(tmp_path, monkeypatch):
    """S18-2: a stop that reports failure proceeds only when the stopped state is verified (health is gone)."""
    from edp8 import update_helper as h
    from test_update_s10 import _staged_msis
    plan = {'kind': 'msi', 'from_version': '0.9.1', 'to_version': '0.9.2', **_staged_msis(tmp_path),
            'install_dir': str(tmp_path), 'upgrade_code': 'synthetic', 'stop_argv': ['s'], 'start_argv': ['s'],
            'health_url': 'http://127.0.0.1:1', 'log': str(tmp_path / 'helper.log')}
    actions, health = [], iter([None, '0.9.2'])
    monkeypatch.setattr(h, '_park', lambda p: [])
    monkeypatch.setattr(h, '_run', lambda p, what, *a, **k: actions.append(what) or what != 'stop')
    monkeypatch.setattr(h, '_close_app', lambda p: None)
    monkeypatch.setattr(h, 'holders', lambda *a, **k: [])
    monkeypatch.setattr(h, '_installed', lambda p: '0.9.2')
    monkeypatch.setattr(h, '_health_version', lambda *a, **k: next(health))
    monkeypatch.setattr(h, '_msiexec', lambda *a: actions.append('msiexec') or 0)
    out = {}
    h._msi_steps(plan, lambda state, reason='', **kw: out.update(state=state) or 0)
    assert 'msiexec' in actions and out['state'] == 'ok'


def test_agent_html_is_head_first(http):
    body = '# Synthetic\n' + 'ordinary background\n' * 1500 + '\n## Tail\nS18TAILMARKER\n'
    did = _doc(http, body=body)
    raw = http.get(f'/v1/docs/{did}', params={'all': 'true'}, headers={'X-Participant': 'eng'})
    assert 'S18TAILMARKER' not in raw.json()['value']['body_md']
    rendered = http.get(f'/v1/docs/{did}/html', headers={'X-Participant': 'eng'})
    assert rendered.status_code in (401, 403) or 'S18TAILMARKER' not in rendered.text, \
        'agent gets whole doc from HTML endpoint despite all=true restriction'


def test_s18_3_agent_html_head_continues_and_a_person_keeps_the_whole_page(http):
    """S18-3: the agent's HTML is the head that doc_read returns, with its continuation; a person gets it whole."""
    body = '# Synthetic\n' + 'ordinary background\n' * 1500 + '\n## Tail\nS18TAILMARKER\n'
    did = _doc(http, body=body)
    v =http.get(f'/v1/docs/{did}/html', headers={'X-Participant': 'eng'}).json()['value']
    assert v['complete'] is False and v['continuation']['page']['offset'] < v['total_chars']
    assert any(s['h'] == '## Tail' for s in v['map'])
    whole = http.get(f'/v1/docs/{did}/html', headers={'X-Participant': 'owner'}).json()['value']
    assert 'S18TAILMARKER' in whole['html'] and 'continuation' not in whole


def _s18_uv_apply(monkeypatch, *, failed=(), board_up=False):
    """The uv/CLI apply path with every service call faked (test_update_s10._uv_apply's rig): the calls made."""
    from pathlib import Path
    from edp8 import launcher, update_helper, updater
    monkeypatch.setenv('EDP_DEV', '0')
    monkeypatch.setattr(launcher, 'bundled', lambda: False)
    monkeypatch.setattr(updater, '_uv_tool_env', lambda: True)
    monkeypatch.setattr(updater, 'current_version', lambda: '1.0.0')
    monkeypatch.setattr(updater, 'fetch_release', lambda url, tag=None: updater.Release('2.0.0', {}))
    monkeypatch.setattr(updater, 'download', lambda rel: {})
    monkeypatch.setattr(updater, 'secure_previous', lambda version, url=None: {'edp8': Path('prev.whl')})
    monkeypatch.setattr(updater, 'backup_db', lambda db, v: Path('b.db'))
    monkeypatch.setattr(updater, '_compat_gate', lambda *a, **k: None)
    monkeypatch.setattr(launcher, 'owner', lambda svc, **k: ('ours', {}))
    monkeypatch.setattr(launcher, 'live_seats', lambda: ['seat-a', 'seat-b'])
    monkeypatch.setattr(updater, '_stage_helper', lambda run: (_ for _ in ()).throw(AssertionError('staged')))
    calls = []

    def park(plan):
        calls.append('park')
        out = update_helper.Parked(['seat-a'])
        out.failed = list(failed)
        return out
    monkeypatch.setattr(update_helper, '_park', park)
    monkeypatch.setattr(update_helper, '_resume_now', lambda plan, hs: calls.append('resume:' + ','.join(hs)) or list(hs))
    monkeypatch.setattr(update_helper, '_health_version', lambda *a, **k: '1.0.0' if board_up else None)
    monkeypatch.setattr(updater, '_stop_all', lambda: calls.append('stop'))
    with pytest.raises(Exception) as got:
        updater.apply({})
    return calls, str(got.value)


def test_s18_2_cli_park_failure_resumes_the_parked_and_installs_nothing(monkeypatch, tmp_path):
    """S18-2 on the uv/CLI path (architect m-45a4207b47): a live seat that fails to park stops the update before
    anything is stopped; the seats already parked are resumed."""
    monkeypatch.setenv('EDP_HOME', str(tmp_path / 'home'))
    calls, why = _s18_uv_apply(monkeypatch, failed=['seat-b'])
    assert calls == ['park', 'resume:seat-a'] and 'seat-b could not be parked' in why


def test_s18_2_cli_stop_that_leaves_the_board_answering_is_refused(monkeypatch, tmp_path):
    """S18-2 on the uv/CLI path: a stop after which the board still answers its health check installs nothing."""
    monkeypatch.setenv('EDP_HOME', str(tmp_path / 'home'))
    calls, why = _s18_uv_apply(monkeypatch, board_up=True)
    assert calls == ['park', 'stop', 'resume:seat-a'] and 'services did not stop' in why
    calls, why = _s18_uv_apply(monkeypatch, board_up=False)  # verified down: it goes on to stage the helper
    assert 'staged' in why


def test_duplicate_sibling_heading_search_roundtrip(http):
    did = _doc(http, body='# Manual\n## Example\nfirst ordinary case\n## Example\ns18uniquesapphire\n')
    hits = _call(http, 'eng', 'find', query='s18uniquesapphire', types='doc')['value']
    hit = next(h for h in hits if h['id'] == did)
    got = _call(http, 'eng', 'doc_read', id=did, section=hit['section'])
    assert got['ok'], f"search selector is not resolvable: {hit['section']}; {got.get('error')}"
    assert 's18uniquesapphire' in got['value']['body_md']


def test_s18_4_repeated_siblings_get_occurrence_selectors_and_readable_paths_stay(http):
    """S18-4: repeated sibling headings read back by `path ⟨n⟩` (the map names them that way), pinned to the version
    they came from; unique headings keep their plain line, and a repeated heading under distinct parents its path."""
    body = ('# Manual\n## Example\nfirst ordinary case\n## Example\nsecond case\n## Setup\nplain\n'
            '# Other\n## Setup\nother setup\n')
    did = _doc(http, body=body)
    # the head read already returned these sections (add05dd2 already-read): re-read them with fresh=True
    head = _call(http, 'eng', 'doc_read', id=did)['value']
    hs = [s['h'] for s in head.get('map', [])] or None
    one = _call(http, 'eng', 'doc_read', id=did, section='# Manual > ## Example ⟨1⟩', fresh=True)['value']
    two = _call(http, 'eng', 'doc_read', id=did, section='# Manual > ## Example ⟨2⟩', version=one['version'], fresh=True)['value']
    assert 'first ordinary case' in one['body_md'] and 'second case' in two['body_md']
    assert _call(http, 'eng', 'doc_read', id=did, section='# Other')['ok']  # a unique line stays plain
    setup = _call(http, 'eng', 'doc_read', id=did, section='# Other > ## Setup', fresh=True)['value']
    assert 'other setup' in setup['body_md']
    bad = _call(http, 'eng', 'doc_read', id=did, section='# Manual > ## Example ⟨3⟩')
    assert not bad['ok'] and 'Example ⟨2⟩' in bad['error']['message']
    from edp8.doc_tools import heading_map
    assert [s['h'] for s in heading_map(body)] == ['# Manual', '# Manual > ## Example ⟨1⟩', '# Manual > ## Example ⟨2⟩',
                                                    '# Manual > ## Setup', '# Other', '# Other > ## Setup']
    assert hs is None or '# Manual > ## Example ⟨2⟩' in hs


def test_s18_4_literal_bracket_heading_path_still_roundtrips(http):
    """S18-4 re-verify (adversary m-60b5706382, ee08e7c4): a heading whose text really ends in `[2]`, under two parents,
    keeps its readable path; the search hit's selector reads it back."""
    did = _doc(http, body='# Manual\n## Example[2]\ns18bracketsapphire\n# Other\n## Example[2]\nother\n')
    hit = next(h for h in _call(http, 'eng', 'find', query='s18bracketsapphire', types='doc')['value'] if h['id'] == did)
    assert hit['section'] == '# Manual > ## Example[2]'
    got = _call(http, 'eng', 'doc_read', id=did, section=hit['section'])
    assert got['ok'], (hit['section'], got.get('error'))
    assert 's18bracketsapphire' in got['value']['body_md']


def test_s18_4_occurrence_selector_never_aliases_a_literal_bracket_path(http):
    """S18-4 re-verify: with duplicate `Example` siblings and a literal `Example[2]` beside them, the literal heading
    reads as itself and each duplicate by its own occurrence selector; no generated selector equals a literal path."""
    body = ('# Manual\n## Example\nfirst\n## Example\nsecond\n'
            '## Example[2]\ns18literalsapphire\n# Other\n## Example[2]\nother\n')
    did = _doc(http, body=body)
    hit = next(h for h in _call(http, 'eng', 'find', query='s18literalsapphire', types='doc')['value'] if h['id'] == did)
    got = _call(http, 'eng', 'doc_read', id=did, section=hit['section'])
    assert got['ok'], (hit['section'], got.get('error'))
    assert 's18literalsapphire' in got['value']['body_md'] and 'second' not in got['value']['body_md']
    two = _call(http, 'eng', 'doc_read', id=did, section='# Manual > ## Example \u27e82\u27e9')['value']
    assert 'second' in two['body_md'] and 's18literalsapphire' not in two['body_md']
    from edp8.doc_tools import heading_map
    hs = [s['h'] for s in heading_map(body)]
    assert len(set(hs)) == len(hs) and '# Manual > ## Example[2]' in hs and '# Other > ## Example[2]' in hs


def test_s18_4_suffix_that_is_itself_a_literal_heading_nests():
    """A heading that literally reads `Example \u27e82\u27e9` cannot capture the generated selector: it nests once more."""
    from edp8.doc_tools import heading_map, _headings, _resolve_section
    body = '# M\n## E\na\n## E\nb\n## E \u27e82\u27e9\nlit\n'
    hs = [s['h'] for s in heading_map(body)]
    assert len(set(hs)) == len(hs), hs
    assert '# M > ## E \u27e82\u27e9 \u27e82\u27e9' in hs
    lines = body.splitlines(keepends=True)
    heads = _headings(lines)
    assert lines[_resolve_section(lines, heads, '# M > ## E \u27e82\u27e9 \u27e82\u27e9') + 1] == 'b\n'
    assert lines[_resolve_section(lines, heads, '## E \u27e82\u27e9') + 1] == 'lit\n'


