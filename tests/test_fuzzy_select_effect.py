#!/usr/bin/env python3
"""Live test: fuzzy_select creates a selection at valid in-bounds coords (Bug #2 regression).

Reads the actual canvas pixel color so the threshold check is independent
of GIMP's edit_fill color encoding on this build.
"""
from tests._harness import cmd, fail, passed, canvas

with canvas(width=200, height=200, fill='white') as idx:
    # Draw a black disk — leaves a distinct background region
    cmd('select_ellipse', {'image_index': idx, 'x': 60, 'y': 60, 'width': 80, 'height': 80})
    cmd('fill_selection', {'image_index': idx, 'color': '#000000'})
    cmd('select_none', {'image_index': idx})

    # Click at (10,10) — in the background region, well inside bounds
    r = cmd('fuzzy_select', {'image_index': idx, 'x': 10, 'y': 10, 'threshold': 15})
    if r.get('status') != 'success':
        fail(f"fuzzy_select error: {r.get('error', '')}")

    bounds = cmd('get_selection_bounds', {'image_index': idx})
    if bounds.get('status') != 'success':
        fail(f"get_selection_bounds error: {bounds.get('error', '')}")
    results = bounds.get('results') or {}
    if not results.get('has_selection'):
        fail(f"has_selection is False after fuzzy_select — selection was not created: {results!r}")

passed(f"fuzzy_select: created selection {results.get('width')}x{results.get('height')}")
