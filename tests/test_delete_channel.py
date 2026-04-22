#!/usr/bin/env python3
"""Live test: delete_channel removes a saved channel."""
from tests._harness import cmd, fail, passed, canvas

with canvas() as idx:
    cmd('select_all', {'image_index': idx})
    cmd('save_selection_as_channel', {'image_index': idx, 'name': '_test_ch_del'})
    r = cmd('delete_channel', {'image_index': idx, 'channel_name': '_test_ch_del'})
    if r.get('status') != 'success':
        fail(f"delete_channel error: {r.get('error', '')}")

passed("delete_channel: removed")
