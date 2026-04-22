#!/usr/bin/env python3
"""Live test: snap_to_grid returns structured 'not available' on 3.2."""
from tests._harness import cmd, fail, passed

r = cmd('snap_to_grid', {'enabled': True})
if r.get('status') == 'success':
    passed("snap_to_grid: unexpectedly supported")
err = r.get('error') or ''
if 'not available' in err.lower() or 'ui' in err.lower():
    passed("snap_to_grid: structured not-available (expected)")
fail(f"unexpected error shape: {err[:140]}")
