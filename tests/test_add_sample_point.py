#!/usr/bin/env python3
"""Live test: add_sample_point drops a sample point at (x, y)."""
from tests._harness import cmd, fail, passed, canvas

with canvas() as idx:
    r = cmd('add_sample_point', {'image_index': idx, 'x': 30, 'y': 30})
    if r.get('status') != 'success':
        fail(f"add_sample_point error: {r.get('error', '')}")
    if not isinstance((r.get('results') or {}).get('sample_point_id'), int):
        fail(f"sample_point_id invalid: {r!r}")

passed(f"add_sample_point: id={(r.get('results') or {}).get('sample_point_id')}")
