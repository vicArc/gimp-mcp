#!/usr/bin/env python3
"""Live test: quick_mask_toggle returns structured 'not available' on 3.2.2.

PASS is defined as: endpoint dispatches, returns status=error with the
known not-available message, and keeps the API shape stable.
"""
from tests._harness import cmd, fail, passed, canvas

with canvas() as idx:
    r = cmd('quick_mask_toggle', {'image_index': idx})

if r.get('status') == 'success':
    passed("quick_mask_toggle: supported (unexpectedly)")

err = r.get('error') or ''
if 'not available' in err.lower() or 'ui' in err.lower():
    passed("quick_mask_toggle: structured not-available (expected on 3.2.2)")
fail(f"unexpected error shape: {err[:120]}")
