#!/usr/bin/env python3
"""Live test: apply_cartoon wraps gegl:cartoon."""
from tests._harness import cmd, fail, passed, canvas

with canvas(fill="#667788") as idx:
    r = cmd('apply_cartoon', {'image_index': idx, 'mask_radius': 5, 'pct_black': 0.15})
    if r.get('status') != 'success':
        fail(f"apply_cartoon error: {r.get('error', '')}")

passed("apply_cartoon: defaults applied")
