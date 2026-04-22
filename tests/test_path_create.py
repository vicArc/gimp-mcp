#!/usr/bin/env python3
"""Live test: path_create makes a bezier path with 3 points."""
from tests._harness import cmd, fail, passed, canvas

with canvas() as idx:
    r = cmd('path_create', {
        'image_index': idx, 'name': '_test_path', 'close': True,
        'points': [
            {'anchor': [10, 10], 'h1': [10, 10], 'h2': [30, 10]},
            {'anchor': [50, 30], 'h1': [40, 20], 'h2': [60, 40]},
            {'anchor': [20, 40], 'h1': [30, 45], 'h2': [20, 40]},
        ],
    })
    if r.get('status') != 'success':
        fail(f"path_create error: {r.get('error', '')}")
    results = r.get('results') or {}
    if not (isinstance(results.get('path_id'), int) and results['path_id'] > 0):
        fail(f"path_id invalid: {results!r}")

passed(f"path_create: path_id={results.get('path_id')} closed=True")
