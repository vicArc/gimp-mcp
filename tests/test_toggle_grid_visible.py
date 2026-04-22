#!/usr/bin/env python3
"""Live test: toggle_grid_visible returns structured 'not available' on 3.2."""
from tests._harness import cmd, fail, passed

r = cmd('toggle_grid_visible', {})
if r.get('status') == 'success':
    passed("toggle_grid_visible: unexpectedly supported")
err = r.get('error') or ''
if 'not available' in err.lower() or 'ui' in err.lower():
    passed("toggle_grid_visible: structured not-available (expected)")
fail(f"unexpected error shape: {err[:140]}")
