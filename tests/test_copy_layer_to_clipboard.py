#!/usr/bin/env python3
"""Live test: copy_layer_to_clipboard copies the active layer."""
from tests._harness import cmd, fail, passed, canvas

with canvas() as idx:
    r = cmd('copy_layer_to_clipboard', {'image_index': idx})
    if r.get('status') != 'success':
        fail(f"copy_layer_to_clipboard error: {r.get('error', '')}")
    if (r.get('results') or {}).get('copied') is not True:
        fail(f"copied not True: {r!r}")

passed("copy_layer_to_clipboard: active layer copied")
