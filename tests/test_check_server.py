#!/usr/bin/env python3
"""Live test: check_server reports running on port 9877."""
from tests._harness import cmd, fail, passed

r = cmd('check_server')
if r.get('status') != 'success':
    fail(f"check_server returned error: {r.get('error', '')}")

results = r.get('results') or {}
if not results.get('running'):
    fail(f"check_server says not running: {results!r}")
if results.get('port') != 9877:
    fail(f"unexpected port: {results!r}")

passed(f"check_server: running on {results.get('port')}")
