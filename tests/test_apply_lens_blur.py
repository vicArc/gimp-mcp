#!/usr/bin/env python3
"""Live test: apply_lens_blur wraps gegl:lens-blur."""
from tests._harness import cmd, fail, passed, canvas

with canvas() as idx:
    r = cmd('apply_lens_blur', {'image_index': idx, 'radius': 3.0})
    if r.get('status') != 'success':
        fail(f"apply_lens_blur error: {r.get('error', '')}")

passed("apply_lens_blur: radius=3.0 applied")
