#!/usr/bin/env python3
"""Live test: adjust_levels applies gimp-drawable-levels."""
from tests._harness import cmd, fail, passed, canvas

with canvas() as idx:
    r = cmd('adjust_levels', {
        'image_index': idx, 'channel': 'value',
        'low_input': 10, 'high_input': 245, 'gamma': 1.2,
        'low_output': 0, 'high_output': 255,
    })
    if r.get('status') != 'success':
        fail(f"adjust_levels error: {r.get('error', '')}")

passed("adjust_levels: value-channel tonal mapping applied")
