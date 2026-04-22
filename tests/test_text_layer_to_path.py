#!/usr/bin/env python3
"""Live test: text_layer_to_path converts a text layer's glyphs to a path."""
from tests._harness import cmd, fail, passed, canvas

with canvas() as idx:
    add = cmd('add_text', {
        'image_index': idx, 'text': 'Hi', 'x': 5, 'y': 5,
        'size': 24, 'color': '#000000',
    })
    if add.get('status') != 'success':
        fail(f"add_text setup failed: {add.get('error', '')}")
    text_layer = (add.get('results') or {}).get('layer_name')
    r = cmd('text_layer_to_path', {
        'image_index': idx, 'text_layer_name': text_layer,
        'new_path_name': '_test_text_path',
    })
    if r.get('status') != 'success':
        fail(f"text_layer_to_path error: {r.get('error', '')}")

passed(f"text_layer_to_path: path={(r.get('results') or {}).get('path_name')}")
