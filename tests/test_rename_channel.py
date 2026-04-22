#!/usr/bin/env python3
"""Live test: rename_channel renames a saved channel."""
from tests._harness import cmd, fail, passed, canvas

with canvas() as idx:
    cmd('select_all', {'image_index': idx})
    cmd('save_selection_as_channel', {'image_index': idx, 'name': '_test_ch_old'})
    r = cmd('rename_channel', {
        'image_index': idx, 'channel_name': '_test_ch_old', 'new_name': '_test_ch_new',
    })
    if r.get('status') != 'success':
        fail(f"rename_channel error: {r.get('error', '')}")
    if (r.get('results') or {}).get('new_name') != '_test_ch_new':
        fail(f"new_name echo mismatch: {r!r}")

passed("rename_channel: renamed")
