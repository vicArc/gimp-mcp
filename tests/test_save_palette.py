#!/usr/bin/env python3
"""Live test: save_palette creates a new palette with given entries."""
from tests._harness import cmd, fail, passed

r = cmd('save_palette', {
    'name': '_test_palette_smoke',
    'colors': [
        {'hex': '#112233', 'name': 'a'},
        {'hex': '#445566', 'name': 'b'},
        '#778899',
    ],
})
if r.get('status') != 'success':
    fail(f"save_palette error: {r.get('error', '')}")
results = r.get('results') or {}
if results.get('entries') != 3:
    fail(f"entries mismatch: {results!r}")
passed(f"save_palette: palette={results.get('palette_name')!r} entries=3")
