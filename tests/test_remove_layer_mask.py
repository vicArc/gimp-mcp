#!/usr/bin/env python3
"""Live test: remove_layer_mask discards an attached mask."""
from tests._harness import cmd, fail, passed, canvas

with canvas() as idx:
    cmd('add_layer_mask', {'image_index': idx, 'mask_type': 'white'})
    r = cmd('remove_layer_mask', {'image_index': idx, 'action': 'discard'})
    if r.get('status') != 'success':
        fail(f"remove_layer_mask error: {r.get('error', '')}")
    if (r.get('results') or {}).get('action') != 'discard':
        fail(f"action echo mismatch: {r!r}")

passed("remove_layer_mask: discarded")
