#!/usr/bin/env python3
"""Live test: raw-socket batch runs a multi-op pipeline plugin-side."""
from tests._harness import cmd, fail, passed, canvas

with canvas() as idx:
    r = cmd('batch', {
        'operations': [
            {'type': 'fill_layer', 'params': {'image_index': idx, 'color': '#112233'}},
            {'type': 'get_canvas_info', 'params': {'image_index': idx}},
            {'type': 'list_layers', 'params': {'image_index': idx}},
        ],
        'stop_on_error': True,
    })
    if r.get('status') != 'success':
        fail(f"batch error: {r.get('error', '')}")
    results = r.get('results') or {}
    if results.get('successes') != 3:
        fail(f"unexpected successes count: {results!r}")

passed(f"batch: 3/3 successes over socket")
