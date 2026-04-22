#!/usr/bin/env python3
"""Live test: get_grid reads current grid settings."""
from tests._harness import cmd, fail, passed, canvas

with canvas() as idx:
    cmd('set_grid', {
        'image_index': idx,
        'spacing_x': 16, 'spacing_y': 16,
        'offset_x': 0, 'offset_y': 0,
    })
    r = cmd('get_grid', {'image_index': idx})
    if r.get('status') != 'success':
        fail(f"get_grid error: {r.get('error', '')}")
    results = r.get('results') or {}
    spacing = results.get('spacing')
    if not spacing or spacing[0] != 16:
        fail(f"spacing mismatch: {results!r}")

passed(f"get_grid: spacing={spacing}")
