#!/usr/bin/env python3
"""Live test: apply_motion_blur dispatches the linear variant."""
from tests._harness import cmd, fail, passed, canvas

with canvas() as idx:
    r = cmd('apply_motion_blur', {
        'image_index': idx, 'length': 8, 'angle': 15, 'type': 'linear',
    })
    if r.get('status') != 'success':
        fail(f"apply_motion_blur error: {r.get('error', '')}")
    if (r.get('results') or {}).get('type') != 'linear':
        fail(f"type echo mismatch: {r!r}")

passed("apply_motion_blur: linear length=8 angle=15 applied")
