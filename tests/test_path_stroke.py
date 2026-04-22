#!/usr/bin/env python3
"""Live test: path_stroke strokes a named path on the active layer."""
from tests._harness import cmd, fail, passed, canvas

with canvas() as idx:
    cmd('path_create', {
        'image_index': idx, 'name': '_test_pstroke', 'close': True,
        'points': [
            {'anchor': [10, 10]}, {'anchor': [50, 10]}, {'anchor': [30, 40]},
        ],
    })
    r = cmd('path_stroke', {
        'image_index': idx, 'path_name': '_test_pstroke', 'size': 3.0,
    })
    if r.get('status') != 'success':
        fail(f"path_stroke error: {r.get('error', '')}")

passed("path_stroke: _test_pstroke stroked")
