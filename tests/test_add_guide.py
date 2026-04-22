#!/usr/bin/env python3
"""Live test: add_guide inserts a horizontal or vertical guide."""
from tests._harness import cmd, fail, passed, canvas

with canvas(width=200, height=150) as idx:
    r = cmd('add_guide', {
        'image_index': idx, 'orientation': 'horizontal', 'position': 40,
    })
    if r.get('status') != 'success':
        fail(f"add_guide error: {r.get('error', '')}")
    if not isinstance((r.get('results') or {}).get('guide_id'), int):
        fail(f"guide_id invalid: {r!r}")

passed(f"add_guide: guide_id={(r.get('results') or {}).get('guide_id')}")
