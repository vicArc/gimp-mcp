#!/usr/bin/env python3
"""Live test: invert_layer_mask flips the mask."""
from tests._harness import cmd, fail, passed, canvas

with canvas() as idx:
    cmd('add_layer_mask', {'image_index': idx, 'mask_type': 'white'})
    r = cmd('invert_layer_mask', {'image_index': idx})
    if r.get('status') != 'success':
        fail(f"invert_layer_mask error: {r.get('error', '')}")

passed("invert_layer_mask: applied")
