#!/usr/bin/env python3
"""Live test: set_grid sets spacing + offset + foreground."""
from tests._harness import cmd, fail, passed, canvas

with canvas() as idx:
    r = cmd('set_grid', {
        'image_index': idx,
        'spacing_x': 20, 'spacing_y': 20,
        'offset_x': 5, 'offset_y': 5,
        'foreground': '#ff0000',
    })
    if r.get('status') != 'success':
        fail(f"set_grid error: {r.get('error', '')}")

passed("set_grid: 20x20 spacing with red fg")
