#!/usr/bin/env python3
"""Live test: list_macros returns recorded macro names."""
from tests._harness import cmd, fail, passed

cmd('record_macro', {'name': '_test_lm_one'})
cmd('stop_recording', {})
r = cmd('list_macros', {})
if r.get('status') != 'success':
    fail(f"list_macros error: {r.get('error', '')}")
macros = (r.get('results') or {}).get('macros') or []
if '_test_lm_one' not in macros:
    fail(f"_test_lm_one missing from list: {macros!r}")

passed(f"list_macros: {len(macros)} macros, _test_lm_one present")
