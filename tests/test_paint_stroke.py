#!/usr/bin/env python3
"""Live test: paint_stroke draws a paintbrush stroke on the active layer."""
from tests._harness import cmd, fail, passed, canvas

with canvas() as idx:
    r = cmd('paint_stroke', {
        'image_index': idx, 'tool': 'paintbrush',
        'size': 4.0, 'opacity': 100, 'color': '#223344',
        'strokes': [10.0, 10.0, 40.0, 30.0, 60.0, 50.0],
    })
    if r.get('status') != 'success':
        fail(f"paint_stroke error: {r.get('error', '')}")
    if (r.get('results') or {}).get('stroke_count') != 3:
        fail(f"stroke_count mismatch: {r!r}")

passed("paint_stroke: paintbrush, 3-point stroke")
