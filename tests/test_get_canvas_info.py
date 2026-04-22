#!/usr/bin/env python3
"""Live test: get_canvas_info returns consolidated image state."""
from tests._harness import cmd, fail, passed, canvas

with canvas(width=200, height=150) as idx:
    r = cmd('get_canvas_info', {'image_index': idx})
    if r.get('status') != 'success':
        fail(f"get_canvas_info returned error: {r.get('error', '')}")
    results = r.get('results') or {}
    if results.get('width') != 200 or results.get('height') != 150:
        fail(f"dimensions mismatch: {results!r}")
    if results.get('color_mode') != 'RGB':
        fail(f"color_mode not RGB: {results.get('color_mode')!r}")
    if results.get('num_layers') != 1:
        fail(f"num_layers not 1 for fresh canvas: {results.get('num_layers')!r}")

passed("get_canvas_info: 200x150 RGB with 1 layer")
