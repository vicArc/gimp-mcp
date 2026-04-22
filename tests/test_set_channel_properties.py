#!/usr/bin/env python3
"""Live test: set_channel_properties tweaks opacity / visibility / color."""
from tests._harness import cmd, fail, passed, canvas

with canvas() as idx:
    cmd('select_all', {'image_index': idx})
    cmd('save_selection_as_channel', {'image_index': idx, 'name': '_test_ch_props'})
    r = cmd('set_channel_properties', {
        'image_index': idx, 'channel_name': '_test_ch_props',
        'opacity': 42.0, 'color': '#ff0000', 'visible': False,
    })
    if r.get('status') != 'success':
        fail(f"set_channel_properties error: {r.get('error', '')}")
    applied = (r.get('results') or {}).get('applied') or {}
    if 'opacity' not in applied:
        fail(f"opacity not applied: {applied!r}")

passed(f"set_channel_properties: applied {sorted(applied.keys())}")
