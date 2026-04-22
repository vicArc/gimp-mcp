#!/usr/bin/env python3
"""Live test: transform_layer scales + translates the active layer."""
from tests._harness import cmd, fail, passed, canvas

with canvas(width=100, height=80) as idx:
    r = cmd('transform_layer', {
        'image_index': idx,
        'scale_width': 60, 'scale_height': 40,
        'offset_x': 5, 'offset_y': 3,
    })
    if r.get('status') != 'success':
        fail(f"transform_layer error: {r.get('error', '')}")
    results = r.get('results') or {}
    if results.get('width') != 60 or results.get('height') != 40:
        fail(f"final size mismatch: {results!r}")

passed(f"transform_layer: scaled to 60x40 at offset ({results.get('offset_x')},{results.get('offset_y')})")
