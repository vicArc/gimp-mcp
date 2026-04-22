#!/usr/bin/env python3
"""Live test: get_dominant_colors returns top-k bucketed colors."""
from tests._harness import cmd, fail, passed, canvas

with canvas(width=60, height=40, fill="#226699") as idx:
    r = cmd('get_dominant_colors', {
        'image_index': idx, 'k': 3, 'sample_size': 24,
    })
    if r.get('status') != 'success':
        fail(f"get_dominant_colors error: {r.get('error', '')}")
    results = r.get('results') or {}
    colors = results.get('colors') or []
    if not colors:
        fail(f"no colors returned: {results!r}")
    for c in colors:
        if 'hex' not in c or 'count' not in c:
            fail(f"color entry missing hex/count: {c!r}")

passed(f"get_dominant_colors: {len(colors)} colors")
