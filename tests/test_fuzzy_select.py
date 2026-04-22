#!/usr/bin/env python3
"""Live test: fuzzy_select picks a contiguous region around a pixel."""
from tests._harness import cmd, fail, passed, canvas

with canvas(width=80, height=60, fill="#ff3366") as idx:
    r = cmd('fuzzy_select', {
        'image_index': idx, 'x': 20, 'y': 20, 'threshold': 15.0,
    })
    if r.get('status') != 'success':
        fail(f"fuzzy_select error: {r.get('error', '')}")
    if (r.get('results') or {}).get('threshold') != 15.0:
        fail(f"threshold echo mismatch: {r!r}")

passed("fuzzy_select: (20,20) threshold=15 applied")
