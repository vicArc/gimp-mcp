#!/usr/bin/env python3
"""Live test: apply_bump_map uses another layer as height source."""
from tests._harness import cmd, fail, passed, canvas

with canvas() as idx:
    cmd('create_layer', {'image_index': idx, 'name': '_bump_src',
                          'width': 120, 'height': 80, 'fill': '#888888'})
    r = cmd('apply_bump_map', {
        'image_index': idx, 'layer_name': None,
        'bump_layer_name': '_bump_src',
        'azimuth': 120, 'elevation': 50, 'depth': 2,
    })
    if r.get('status') != 'success':
        fail(f"apply_bump_map error: {r.get('error', '')}")

passed("apply_bump_map: _bump_src applied")
