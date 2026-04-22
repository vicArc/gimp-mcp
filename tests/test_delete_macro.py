#!/usr/bin/env python3
"""Live test: delete_macro drops a previously recorded macro."""
from tests._harness import cmd, fail, passed

cmd('record_macro', {'name': '_test_dm'})
cmd('stop_recording', {})
r = cmd('delete_macro', {'name': '_test_dm'})
if r.get('status') != 'success':
    fail(f"delete_macro error: {r.get('error', '')}")

passed("delete_macro: _test_dm dropped")
