#!/usr/bin/env python3
"""Live test: create_brush_from_selection returns the 'not available' stub on 3.2."""
from tests._harness import cmd, fail, passed

r = cmd('create_brush_from_selection', {'name': '_nope'})
if r.get('status') == 'success':
    passed("create_brush_from_selection: unexpectedly supported")
err = r.get('error') or ''
if 'not available' in err.lower() or 'no direct pdb' in err.lower() or 'workflow' in err.lower():
    passed("create_brush_from_selection: structured not-available (expected)")
fail(f"unexpected error shape: {err[:140]}")
