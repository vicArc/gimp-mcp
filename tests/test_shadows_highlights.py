#!/usr/bin/env python3
"""Live test: shadows_highlights applies gegl:shadows-highlights."""
from tests._harness import cmd, fail, passed, canvas

with canvas() as idx:
    r = cmd('shadows_highlights', {
        'image_index': idx,
        'shadow_amount': 30, 'highlight_amount': -20,
        'radius': 25, 'color_correction': 15,
    })
    if r.get('status') != 'success':
        fail(f"shadows_highlights error: {r.get('error', '')}")
    if (r.get('results') or {}).get('shadow_amount') != 30:
        fail(f"echo mismatch: {r!r}")

passed("shadows_highlights: 30/-20 applied")
