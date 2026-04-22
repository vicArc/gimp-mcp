#!/usr/bin/env python3
"""Live test: apply_filter_nondestructive stacks a live filter."""
from tests._harness import cmd, fail, passed, canvas

with canvas() as idx:
    r = cmd('apply_filter_nondestructive', {
        'image_index': idx, 'operation': 'gegl:gaussian-blur',
        'properties': {'std-dev-x': 1.5, 'std-dev-y': 1.5},
    })
    if r.get('status') != 'success':
        fail(f"apply_filter_nondestructive error: {r.get('error', '')}")
    results = r.get('results') or {}
    if not isinstance(results.get('filter_id'), int):
        fail(f"filter_id missing: {results!r}")

passed(f"apply_filter_nondestructive: filter_id={results.get('filter_id')}")
