#!/usr/bin/env python3
"""Live test: paste_from_clipboard pastes clipboard content as a new layer."""
from tests._harness import cmd, fail, passed, canvas

with canvas() as idx:
    cmd('select_all', {'image_index': idx})
    cmd('copy_selection_to_clipboard', {'image_index': idx})
    r = cmd('paste_from_clipboard', {
        'image_index': idx, 'as_new_layer': True, 'layer_name': '_test_pasted',
    })
    if r.get('status') != 'success':
        fail(f"paste_from_clipboard error: {r.get('error', '')}")

passed("paste_from_clipboard: pasted as new layer")
