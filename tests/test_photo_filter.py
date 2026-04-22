#!/usr/bin/env python3
"""Live test: photo_filter overlay merge succeeds on a flat canvas."""
from tests._harness import cmd, fail, passed, canvas

with canvas(fill="white") as idx:
    r = cmd('photo_filter', {
        'image_index': idx,
        'color': '#ffaa55', 'density': 20,
    })
    if r.get('status') != 'success':
        fail(f"photo_filter error: {r.get('error', '')}")

passed("photo_filter: warming overlay merged")
