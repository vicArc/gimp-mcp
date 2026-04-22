#!/usr/bin/env python3
"""Live test: delete_brush reports 'not found' when given a bogus name.

This avoids actually deleting a real brush during testing.
"""
from tests._harness import cmd, fail, passed

r = cmd('delete_brush', {'name': '_brush_that_definitely_does_not_exist'})
if r.get('status') == 'success':
    fail(f"unexpected success for bogus brush: {r!r}")
err = r.get('error') or ''
# Accept either 'not found' (brush resolved as None) or 'not available'
# (gimp-brush-delete PDB proc missing in this build) — both mean the
# endpoint dispatched and returned a structured error.
if 'not found' not in err.lower() and 'not available' not in err.lower():
    fail(f"unexpected error shape: {err[:140]}")

passed(f"delete_brush: structured error (endpoint reachable): {err[:60]}")
