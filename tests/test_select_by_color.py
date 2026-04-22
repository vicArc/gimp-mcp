#!/usr/bin/env python3
"""Live test: select_by_color actually creates a selection (Bug #1 regression).

Tests the fundamental behavior: given pixels of known color X, selecting
by color X produces a non-empty selection. Uses get_pixel_color to obtain
the actual canvas fill color instead of assuming exact hex round-trips,
since edit_fill has a color-encoding quirk in GIMP 3.2.2 on Windows.
"""
from tests._harness import cmd, fail, passed, canvas

with canvas(width=200, height=200, fill='white') as idx:
    # Draw a distinct foreground region so we have two color zones
    cmd('select_ellipse', {'image_index': idx, 'x': 60, 'y': 60, 'width': 80, 'height': 80})
    cmd('fill_selection', {'image_index': idx, 'color': '#000000'})
    cmd('select_none', {'image_index': idx})

    # Read the actual background pixel color (top-left corner, outside the disk)
    pc = cmd('get_pixel_color', {'image_index': idx, 'x': 5, 'y': 5})
    if pc.get('status') != 'success':
        fail(f"get_pixel_color failed: {pc.get('error', '')}")
    actual_hex = (pc.get('results') or {}).get('color_hex', '#ffffff')

    # select_by_color using the actual canvas color — threshold of 5 should hit it
    r = cmd('select_by_color', {'image_index': idx, 'color': actual_hex, 'threshold': 5})
    if r.get('status') != 'success':
        fail(f"select_by_color returned error: {r.get('error', '')}")

    bounds = cmd('get_selection_bounds', {'image_index': idx})
    if bounds.get('status') != 'success':
        fail(f"get_selection_bounds error: {bounds.get('error', '')}")
    results = bounds.get('results') or {}
    if not results.get('has_selection'):
        fail(f"has_selection is False after select_by_color (color={actual_hex}) — selection was not created: {results!r}")
    if results.get('width', 0) == 0 or results.get('height', 0) == 0:
        fail(f"selection has zero size: {results!r}")

passed(f"select_by_color: created selection {results.get('width')}x{results.get('height')} for color {actual_hex}")
