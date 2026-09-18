"""Cold-start integrated native fixture smoke, not native browser evidence."""
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import time
from urllib.request import urlopen


def test_native_harness_serves_integrated_ui_and_emits_requests(tmp_path):
    script = Path(__file__).resolve().parents[1] / 'docs/s5-notifications/native_harness.py'
    with socket.socket() as sock:
        sock.bind(('127.0.0.1', 0))
        port = sock.getsockname()[1]
    manifest = tmp_path / 'manifest.json'
    process = subprocess.Popen([sys.executable, str(script), 'serve', '--port', str(port), '--manifest', str(manifest)], stdout=subprocess.PIPE, stderr=subprocess.STDOUT, env={**os.environ, 'TEMP': str(tmp_path), 'TMP': str(tmp_path)})
    try:
        for _ in range(100):
            if process.poll() is not None:
                raise AssertionError(process.stdout.read().decode())
            try:
                with urlopen(f'http://127.0.0.1:{port}/healthz', timeout=.2) as response:
                    assert response.status == 200
                break
            except OSError:
                time.sleep(.1)
        else:
            raise AssertionError('fixture did not start')
        with urlopen(f'http://127.0.0.1:{port}/ui/notifications-worker.js') as response:
            assert 'javascript' in response.headers['content-type']
            assert response.headers['cache-control'] == 'no-store'
            assert b'notificationclick' in response.read()
        for mode in ([], ['--approval']):
            result = subprocess.run([sys.executable, str(script), 'emit', '--manifest', str(manifest), *mode], capture_output=True, text=True, timeout=20)
            assert result.returncode == 0, result.stderr
            value = json.loads(result.stdout)
            assert value['source'].startswith('epic-')
            assert value['kind'] == ('approval' if mode else 'question')
    finally:
        process.terminate()  # only this owned foreground fixture, never process-name based
        process.wait(timeout=10)
