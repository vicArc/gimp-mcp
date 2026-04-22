#!/usr/bin/env python3
"""Live test: apply_unsharp_mask wraps gegl:unsharp-mask."""
from tests._harness import cmd, fail, passed, canvas

with canvas() as idx:
    r = cmd('apply_unsharp_mask', {
        'image_index': idx, 'radius': 2.0, 'amount': 0.5, 'threshold': 0.0,
    })
    if r.get('status') != 'success':
        fail(f"apply_unsharp_mask error: {r.get('error', '')}")

passed("apply_unsharp_mask: defaults applied")
