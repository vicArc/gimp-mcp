#!/usr/bin/env python3
"""Live test: apply_waterpixels wraps gegl:waterpixels."""
from tests._harness import cmd, fail, passed, canvas

with canvas(fill="#223344") as idx:
    r = cmd('apply_waterpixels', {'image_index': idx, 'size': 10, 'smoothness': 1.0})
    if r.get('status') != 'success':
        fail(f"apply_waterpixels error: {r.get('error', '')}")

passed("apply_waterpixels: size=10 applied")
