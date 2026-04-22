#!/usr/bin/env python3
"""Live test: duplicate_channel copies a named channel."""
from tests._harness import cmd, fail, passed, canvas

with canvas() as idx:
    cmd('select_all', {'image_index': idx})
    cmd('save_selection_as_channel', {'image_index': idx, 'name': '_test_dup_src'})
    r = cmd('duplicate_channel', {
        'image_index': idx, 'channel_name': '_test_dup_src', 'new_name': '_test_dup_copy',
    })
    if r.get('status') != 'success':
        fail(f"duplicate_channel error: {r.get('error', '')}")

passed(f"duplicate_channel: new={(r.get('results') or {}).get('new_name')}")
