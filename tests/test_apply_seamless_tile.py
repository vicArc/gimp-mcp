#!/usr/bin/env python3
"""Live test: apply_seamless_tile wraps gegl:tile-seamless."""
from tests._harness import cmd, fail, passed, canvas

with canvas(fill="#abcdef") as idx:
    r = cmd('apply_seamless_tile', {'image_index': idx})
    if r.get('status') != 'success':
        fail(f"apply_seamless_tile error: {r.get('error', '')}")

passed("apply_seamless_tile: applied")
