#!/usr/bin/env python3
"""Live test: fill_selection(fill_type='foreground') works without explicit color (Bug #4 regression)."""
from tests._harness import cmd, fail, passed, canvas

with canvas(width=100, height=100, fill='white') as idx:
    # Set a distinctive foreground color via set_colors, then fill without passing color=
    cmd('set_colors', {'foreground': '#e8b99a'})
    cmd('select_rectangle', {'image_index': idx, 'x': 10, 'y': 10, 'width': 80, 'height': 80})

    # This must NOT crash with "Argument 0 does not allow None as a value"
    r = cmd('fill_selection', {'image_index': idx, 'layer_name': None, 'fill_type': 'foreground'})
    if r.get('status') != 'success':
        fail(f"fill_selection(fill_type=foreground) failed: {r.get('error', r)}")

    # Also verify that passing color=None explicitly doesn't crash
    cmd('select_rectangle', {'image_index': idx, 'x': 10, 'y': 10, 'width': 40, 'height': 40})
    r2 = cmd('fill_selection', {'image_index': idx, 'fill_type': 'foreground', 'color': None})
    if r2.get('status') != 'success':
        fail(f"fill_selection(color=None) failed: {r2.get('error', r2)}")

passed("fill_selection: foreground fill without explicit color works correctly")
