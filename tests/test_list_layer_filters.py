#!/usr/bin/env python3
"""Live test: list_layer_filters enumerates live filters."""
from tests._harness import cmd, fail, passed, canvas

with canvas() as idx:
    cmd('apply_filter_nondestructive', {
        'image_index': idx, 'operation': 'gegl:gaussian-blur',
        'properties': {'std-dev-x': 1.0, 'std-dev-y': 1.0},
    })
    r = cmd('list_layer_filters', {'image_index': idx})
    if r.get('status') != 'success':
        fail(f"list_layer_filters error: {r.get('error', '')}")
    results = r.get('results') or {}
    if (results.get('count') or 0) < 1:
        fail(f"expected >=1 filter: {results!r}")

passed(f"list_layer_filters: count={results.get('count')}")
