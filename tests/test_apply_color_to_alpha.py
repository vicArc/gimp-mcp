#!/usr/bin/env python3
"""Live test: apply_color_to_alpha wraps gegl:color-to-alpha."""
from tests._harness import cmd, fail, passed, canvas

with canvas(fill="white") as idx:
    r = cmd('apply_color_to_alpha', {
        'image_index': idx, 'color': 'white',
        'transparency_threshold': 0.0, 'opacity_threshold': 1.0,
    })
    if r.get('status') != 'success':
        fail(f"apply_color_to_alpha error: {r.get('error', '')}")

passed("apply_color_to_alpha: drop white applied")
