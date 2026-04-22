#!/usr/bin/env python3
"""Live test: duplicate_image clones an image and returns the new index."""
from tests._harness import cmd, fail, passed, canvas

with canvas(width=64, height=48) as idx:
    r = cmd('duplicate_image', {'image_index': idx})
    if r.get('status') != 'success':
        fail(f"duplicate_image returned error: {r.get('error', '')}")
    results = r.get('results') or {}
    new_id   = results.get('new_image_id')
    src_id   = results.get('source_image_id')
    new_idx  = results.get('new_image_index')
    if not (isinstance(new_id, int) and new_id > 0):
        fail(f"new_image_id invalid: {new_id!r}")
    if not (isinstance(src_id, int) and src_id > 0):
        fail(f"source_image_id invalid: {src_id!r}")
    if new_id == src_id:
        fail("duplicate returned the source image id")
    cmd('close_image', {'image_index': new_idx, 'save_first': False})

passed(f"duplicate_image: source={src_id} -> new={new_id}")
