#!/usr/bin/env python3
"""Live test: set_path_visible toggles a path's visibility."""
from tests._harness import cmd, fail, passed, canvas

with canvas() as idx:
    cmd('path_create', {
        'image_index': idx, 'name': '_test_pv',
        'points': [{'anchor': [10, 10]}, {'anchor': [50, 50]}],
    })
    r = cmd('set_path_visible', {
        'image_index': idx, 'path_name': '_test_pv', 'visible': False,
    })
    if r.get('status') != 'success':
        fail(f"set_path_visible error: {r.get('error', '')}")
    if (r.get('results') or {}).get('visible') is not False:
        fail(f"visible echo mismatch: {r!r}")

passed("set_path_visible: visible=False")
