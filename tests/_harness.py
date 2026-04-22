"""Shared test harness for per-tool live-GIMP tests.

Every per-tool test imports `send`, `cmd`, `fail`, `require`, and the
`canvas` context manager from here and keeps assertions focused on
the endpoint under test.

Usage:
    from tests._harness import cmd, fail, require, canvas

    with canvas(width=100, height=60) as idx:
        r = cmd('<tool-name>', {'image_index': idx, ...})
        require(r, {'status': 'success'})
        results = r.get('results') or {}
        if not results.get('<expected-field>'):
            fail("missing <expected-field>")
"""
from __future__ import annotations

import json
import socket
import sys
from contextlib import contextmanager

HOST, PORT = '127.0.0.1', 9877
DEFAULT_TIMEOUT = 30


def send(msg, timeout=DEFAULT_TIMEOUT):
    """Send one JSON message to the MCP socket and return the reply."""
    s = socket.socket()
    s.settimeout(timeout)
    s.connect((HOST, PORT))
    s.send(json.dumps(msg).encode() + b'\n')
    buf = b''
    while True:
        try:
            chunk = s.recv(65536)
            if not chunk:
                break
            buf += chunk
            try:
                json.loads(buf.decode())
                break
            except json.JSONDecodeError:
                continue
        except socket.timeout:
            break
    s.close()
    try:
        return json.loads(buf.decode().strip())
    except json.JSONDecodeError:
        return {'status': 'error', 'error': 'parse: ' + buf.decode()[:200]}


def cmd(t, params=None):
    """Send a {type, params} command."""
    return send({'type': t, 'params': params or {}})


def fail(msg):
    """Abort with a failure banner on stderr."""
    print(f"FAIL: {msg}", file=sys.stderr)
    sys.exit(1)


def passed(msg=""):
    """Emit a success line and exit 0."""
    print(f"PASS{(' ' + msg) if msg else ''}")
    sys.exit(0)


def require(resp, expected):
    """Assert keys in the response; fail with a human summary if not."""
    if not isinstance(resp, dict):
        fail(f"response is not a dict: {resp!r}")
    for key, want in expected.items():
        if key not in resp:
            fail(f"missing key {key!r} in {resp!r}")
        if resp[key] != want:
            fail(f"{key}={resp[key]!r} (expected {want!r}): {str(resp.get('error', ''))[:120]}")


@contextmanager
def canvas(width=120, height=80, fill="white"):
    """Create a scratch canvas, yield its image_index, close on exit."""
    r = cmd('new_canvas', {'width': width, 'height': height, 'fill': fill})
    if r.get('status') != 'success':
        fail(f"canvas setup failed: {r.get('error', '')}")
    image_id = r.get('image_id') or (r.get('results') or {}).get('image_id')
    li = cmd('list_images', {})
    images = (li.get('results') or {}).get('images') or []
    idx = next((i for i, info in enumerate(images)
                if isinstance(info, dict) and info.get('image_id') == image_id), 0)
    try:
        yield idx
    finally:
        try:
            cmd('close_image', {'image_index': idx, 'save_first': False})
        except Exception:
            pass
