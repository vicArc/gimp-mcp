#!/usr/bin/env python3
"""Live test: adjust_threshold applies gimp-drawable-threshold."""
from tests._harness import cmd, fail, passed, canvas

with canvas(width=80, height=60, fill="#808080") as idx:
    r = cmd('adjust_threshold', {'image_index': idx, 'low': 0.3, 'high': 0.7})
    if r.get('status') != 'success':
        fail(f"adjust_threshold error: {r.get('error', '')}")
    results = r.get('results') or {}
    if results.get('low') != 0.3 or results.get('high') != 0.7:
        fail(f"echo mismatch: {results!r}")

passed("adjust_threshold: low=0.3 high=0.7 applied")
