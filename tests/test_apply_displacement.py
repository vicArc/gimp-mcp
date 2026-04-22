#!/usr/bin/env python3
"""Live test: apply_displacement warps using x/y map layers."""
from tests._harness import cmd, fail, passed, canvas

with canvas() as idx:
    cmd('create_layer', {'image_index': idx, 'name': '_disp_src',
                          'width': 120, 'height': 80, 'fill': '#555555'})
    r = cmd('apply_displacement', {
        'image_index': idx, 'layer_name': None,
        'x_map_layer': '_disp_src', 'y_map_layer': '_disp_src',
        'amount': 5.0, 'edge_behavior': 'wrap',
    })
    if r.get('status') != 'success':
        fail(f"apply_displacement error: {r.get('error', '')}")

passed("apply_displacement: wrap mode applied")
