#!/usr/bin/env python3
"""Live test: delete_pattern reports a structured error for a bogus name."""
from tests._harness import cmd, fail, passed

r = cmd('delete_pattern', {'name': '_pattern_that_does_not_exist'})
if r.get('status') == 'success':
    fail(f"unexpected success: {r!r}")
err = r.get('error') or ''
if 'not found' not in err.lower() and 'not available' not in err.lower():
    fail(f"unexpected error shape: {err[:140]}")

passed("delete_pattern: structured error (endpoint reachable)")
