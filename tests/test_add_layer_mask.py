#!/usr/bin/env python3
"""Live test: add_layer_mask attaches a white mask."""
from tests._harness import cmd, fail, passed, canvas

with canvas() as idx:
    r = cmd('add_layer_mask', {'image_index': idx, 'mask_type': 'white'})
    if r.get('status') != 'success':
        fail(f"add_layer_mask error: {r.get('error', '')}")
    results = r.get('results') or {}
    if not isinstance(results.get('mask_id'), int) or results.get('mask_id') <= 0:
        fail(f"mask_id invalid: {results!r}")
    if results.get('mask_type') != 'white':
        fail(f"mask_type mismatch: {results!r}")

passed(f"add_layer_mask: mask_id={results.get('mask_id')}")
