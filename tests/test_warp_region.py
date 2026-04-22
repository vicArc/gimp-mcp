#!/usr/bin/env python3
"""Live test: warp_region doesn't corrupt layer to solid black (Bug regression)."""
from tests._harness import cmd, fail, passed, canvas

with canvas(width=200, height=200, fill='white') as idx:
    # Paint a colored background so we have non-black content
    cmd('fill_layer', {'image_index': idx, 'color': '#8844ff'})

    # Apply a warp vector in the centre
    r = cmd('warp_region', {
        'image_index': idx,
        'vectors': [{'x': 100, 'y': 100, 'dx': 10, 'dy': 5,
                     'radius': 30, 'amount': 0.4}],
    })
    if r.get('status') != 'success':
        fail(f"warp_region failed: {r.get('error', r)}")

    # Sample pixel — must NOT be solid black
    pc = cmd('get_pixel_color', {'image_index': idx, 'x': 50, 'y': 50})
    if pc.get('status') != 'success':
        fail(f"get_pixel_color failed: {pc.get('error', pc)}")
    hex_val = (pc.get('results') or {}).get('color_hex', '#000000')
    if hex_val in ('#000000', '#010101', '#020202'):
        fail(f"pixel is solid black ({hex_val}) — layer was corrupted by warp_region")

passed(f"warp_region: layer not corrupted, pixel={hex_val}")
