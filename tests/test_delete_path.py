#!/usr/bin/env python3
"""Live test: delete_path removes a named path."""
from tests._harness import cmd, fail, passed, canvas

with canvas() as idx:
    cmd('path_create', {
        'image_index': idx, 'name': '_test_dp',
        'points': [{'anchor': [10, 10]}, {'anchor': [50, 50]}],
    })
    r = cmd('delete_path', {'image_index': idx, 'path_name': '_test_dp'})
    if r.get('status') != 'success':
        fail(f"delete_path error: {r.get('error', '')}")

passed("delete_path: removed")
