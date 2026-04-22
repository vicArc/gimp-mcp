#!/usr/bin/env python3
"""Live test: remove_all_guides clears every guide."""
from tests._harness import cmd, fail, passed, canvas

with canvas() as idx:
    for pos in (10, 30, 50):
        cmd('add_guide', {'image_index': idx, 'orientation': 'horizontal', 'position': pos})
    r = cmd('remove_all_guides', {'image_index': idx})
    if r.get('status') != 'success':
        fail(f"remove_all_guides error: {r.get('error', '')}")
    if (r.get('results') or {}).get('removed') != 3:
        fail(f"removed count mismatch: {r!r}")

passed("remove_all_guides: 3 guides cleared")
