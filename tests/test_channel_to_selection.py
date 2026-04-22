#!/usr/bin/env python3
"""Live test: channel_to_selection loads a saved channel into the selection."""
from tests._harness import cmd, fail, passed, canvas

with canvas() as idx:
    cmd('select_all', {'image_index': idx})
    cmd('save_selection_as_channel', {'image_index': idx, 'name': '_test_ch2sel'})
    r = cmd('channel_to_selection', {
        'image_index': idx, 'channel_name': '_test_ch2sel', 'operation': 'replace',
    })
    if r.get('status') != 'success':
        fail(f"channel_to_selection error: {r.get('error', '')}")

passed("channel_to_selection: _test_ch2sel loaded")
