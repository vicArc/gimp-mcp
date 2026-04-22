#!/usr/bin/env python3
"""Live test: list_sample_points enumerates sample points."""
from tests._harness import cmd, fail, passed, canvas

with canvas() as idx:
    cmd('add_sample_point', {'image_index': idx, 'x': 10, 'y': 10})
    cmd('add_sample_point', {'image_index': idx, 'x': 50, 'y': 40})
    r = cmd('list_sample_points', {'image_index': idx})
    if r.get('status') != 'success':
        fail(f"list_sample_points error: {r.get('error', '')}")
    if (r.get('results') or {}).get('count') != 2:
        fail(f"expected 2 sample points: {r!r}")

passed("list_sample_points: 2 points")
