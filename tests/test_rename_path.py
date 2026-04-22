#!/usr/bin/env python3
"""Live test: rename_path renames an existing path."""
from tests._harness import cmd, fail, passed, canvas

with canvas() as idx:
    cmd('path_create', {
        'image_index': idx, 'name': '_test_rp_old',
        'points': [{'anchor': [10, 10]}, {'anchor': [50, 50]}],
    })
    r = cmd('rename_path', {
        'image_index': idx, 'path_name': '_test_rp_old', 'new_name': '_test_rp_new',
    })
    if r.get('status') != 'success':
        fail(f"rename_path error: {r.get('error', '')}")

passed("rename_path: renamed")
