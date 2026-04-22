#!/usr/bin/env python3
"""Live test: apply_oilify wraps gegl:oilify."""
from tests._harness import cmd, fail, passed, canvas

with canvas(fill="#887766") as idx:
    r = cmd('apply_oilify', {'image_index': idx, 'mask_radius': 3})
    if r.get('status') != 'success':
        fail(f"apply_oilify error: {r.get('error', '')}")

passed("apply_oilify: mask_radius=3 applied")
