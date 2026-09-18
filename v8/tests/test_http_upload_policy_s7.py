"""Single-host shared MCP uploads; isolated servers and operator policy only."""
import json

from test_mcp_http import stack, _run, _call


def test_http_upload_disabled_baseline(stack):
    _, result = _run(_call(stack['mcp'] + '/mcp/engineer', {'X-Participant': 'eng.s1'},
                           'artifact_upload', path='C:/not-opened.txt'))
    out = json.loads(result.content[0].text)
    assert not out['ok'] and out['error']['code'] == 'unavailable'
