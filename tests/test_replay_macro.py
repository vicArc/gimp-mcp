#!/usr/bin/env python3
"""Live test: replay_macro runs a previously recorded macro.

Since record_macro's hook into execute_command is a follow-up, replaying
an 'empty' recorded macro should still succeed with zero steps.
"""
from tests._harness import cmd, fail, passed

cmd('record_macro', {'name': '_test_replay'})
cmd('stop_recording', {})
r = cmd('replay_macro', {'name': '_test_replay'})
if r.get('status') != 'success':
    fail(f"replay_macro error: {r.get('error', '')}")

passed(f"replay_macro: _test_replay steps={(r.get('results') or {}).get('steps')}")
