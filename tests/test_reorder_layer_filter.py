#!/usr/bin/env python3
"""Live test: reorder_layer_filter returns structured 'not available' on 3.2."""
from tests._harness import cmd, fail, passed

r = cmd('reorder_layer_filter', {'filter_id': 1, 'new_position': 0})
if r.get('status') == 'success':
    passed("reorder_layer_filter: unexpectedly supported")
err = r.get('error') or ''
if 'not available' in err.lower() or 'no reorder api' in err.lower() or 'remove_layer_filter' in err.lower():
    passed("reorder_layer_filter: structured not-available (expected)")
fail(f"unexpected error shape: {err[:140]}")
