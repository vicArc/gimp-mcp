#!/usr/bin/env python3
"""Live test: stop_recording closes an active macro."""
from tests._harness import cmd, fail, passed

cmd('record_macro', {'name': '_test_stopmac'})
r = cmd('stop_recording', {})
if r.get('status') != 'success':
    fail(f"stop_recording error: {r.get('error', '')}")
if (r.get('results') or {}).get('name') != '_test_stopmac':
    fail(f"name mismatch: {r!r}")

passed("stop_recording: _test_stopmac closed")
