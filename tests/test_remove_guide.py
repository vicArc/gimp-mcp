#!/usr/bin/env python3
"""Live test: remove_guide deletes one guide by id."""
from tests._harness import cmd, fail, passed, canvas

with canvas() as idx:
    a = cmd('add_guide', {'image_index': idx, 'orientation': 'vertical', 'position': 50})
    gid = (a.get('results') or {}).get('guide_id')
    r = cmd('remove_guide', {'image_index': idx, 'guide_id': gid})
    if r.get('status') != 'success':
        fail(f"remove_guide error: {r.get('error', '')}")

passed(f"remove_guide: guide_id={gid} removed")
