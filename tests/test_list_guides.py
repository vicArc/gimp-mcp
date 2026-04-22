#!/usr/bin/env python3
"""Live test: list_guides enumerates guides on the image."""
from tests._harness import cmd, fail, passed, canvas

with canvas() as idx:
    cmd('add_guide', {'image_index': idx, 'orientation': 'vertical', 'position': 30})
    cmd('add_guide', {'image_index': idx, 'orientation': 'horizontal', 'position': 20})
    r = cmd('list_guides', {'image_index': idx})
    if r.get('status') != 'success':
        fail(f"list_guides error: {r.get('error', '')}")
    if (r.get('results') or {}).get('count') != 2:
        fail(f"expected 2 guides: {r!r}")

passed("list_guides: 2 guides")
