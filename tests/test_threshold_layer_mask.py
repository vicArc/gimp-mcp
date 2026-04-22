#!/usr/bin/env python3
"""Live test: threshold_layer_mask binarizes an existing mask."""
from tests._harness import cmd, fail, passed, canvas

with canvas() as idx:
    cmd('add_layer_mask', {'image_index': idx, 'mask_type': 'white'})
    r = cmd('threshold_layer_mask', {
        'image_index': idx, 'low': 0.5, 'high': 1.0,
    })
    if r.get('status') != 'success':
        fail(f"threshold_layer_mask error: {r.get('error', '')}")
    results = r.get('results') or {}
    if results.get('low') != 0.5 or results.get('high') != 1.0:
        fail(f"echo mismatch: {results!r}")

passed("threshold_layer_mask: 0.5..1.0 applied")
