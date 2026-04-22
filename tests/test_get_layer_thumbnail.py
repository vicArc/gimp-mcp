#!/usr/bin/env python3
"""Live test: get_layer_thumbnail returns a base64 PNG."""
from tests._harness import cmd, fail, passed, canvas

with canvas() as idx:
    r = cmd('get_layer_thumbnail', {'image_index': idx, 'max_size': 32})
    if r.get('status') != 'success':
        fail(f"get_layer_thumbnail error: {r.get('error', '')}")
    results = r.get('results') or {}
    if results.get('mime_type') != 'image/png':
        fail(f"mime_type wrong: {results!r}")
    b64 = results.get('data_base64') or ''
    if len(b64) < 40:
        fail(f"data_base64 too short: {len(b64)}")
    size = results.get('size_bytes') or 0
    if size <= 0:
        fail(f"size_bytes invalid: {size!r}")

passed(f"get_layer_thumbnail: {results.get('width')}x{results.get('height')} {size}B")
