#!/usr/bin/env python3
"""Live test: record_macro starts capturing a named macro."""
from tests._harness import cmd, fail, passed

cmd('stop_recording', {})  # cleanup previous active
r = cmd('record_macro', {'name': '_test_macro'})
if r.get('status') != 'success':
    fail(f"record_macro error: {r.get('error', '')}")
if not (r.get('results') or {}).get('active'):
    fail(f"macro not active: {r!r}")
cmd('stop_recording', {})

passed("record_macro: _test_macro active")
