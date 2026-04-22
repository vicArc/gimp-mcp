#!/usr/bin/env python3
"""Live test: path_to_selection loads a named path into the selection."""
from tests._harness import cmd, fail, passed, canvas

with canvas() as idx:
    cmd('path_create', {
        'image_index': idx, 'name': '_test_p2s', 'close': True,
        'points': [
            {'anchor': [10, 10]}, {'anchor': [50, 10]},
            {'anchor': [50, 40]}, {'anchor': [10, 40]},
        ],
    })
    r = cmd('path_to_selection', {
        'image_index': idx, 'path_name': '_test_p2s', 'operation': 'replace',
    })
    if r.get('status') != 'success':
        fail(f"path_to_selection error: {r.get('error', '')}")

passed("path_to_selection: _test_p2s loaded")
