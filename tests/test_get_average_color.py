#!/usr/bin/env python3
"""Live test: get_average_color samples the mean RGBA of a region."""
from tests._harness import cmd, fail, passed, canvas

with canvas(width=100, height=100, fill="#404080") as idx:
    r = cmd('get_average_color', {
        'image_index': idx, 'x': 10, 'y': 10, 'width': 50, 'height': 50,
    })
    if r.get('status') != 'success':
        fail(f"get_average_color error: {r.get('error', '')}")
    results = r.get('results') or {}
    rgba = results.get('rgba') or []
    if len(rgba) != 4:
        fail(f"rgba missing / wrong length: {rgba!r}")
    if not results.get('hex'):
        fail(f"hex missing: {results!r}")

passed(f"get_average_color: hex={results.get('hex')}")
