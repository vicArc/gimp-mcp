#!/usr/bin/env python3
"""Live test: list_paths returns a list of paths (possibly empty)."""
from tests._harness import cmd, fail, passed, canvas

with canvas() as idx:
    cmd('path_create', {
        'image_index': idx, 'name': '_test_lp',
        'points': [{'anchor': [10, 10]}, {'anchor': [50, 50]}],
    })
    r = cmd('list_paths', {'image_index': idx})
    if r.get('status') != 'success':
        fail(f"list_paths error: {r.get('error', '')}")
    results = r.get('results') or {}
    if (results.get('count') or 0) < 1:
        fail(f"no paths returned: {results!r}")

passed(f"list_paths: count={results.get('count')}")
