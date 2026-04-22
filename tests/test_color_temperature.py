#!/usr/bin/env python3
"""Live test: color_temperature applies gegl:color-temperature."""
from tests._harness import cmd, fail, passed, canvas

with canvas() as idx:
    r = cmd('color_temperature', {'image_index': idx, 'kelvin': 4000, 'tint': 5})
    if r.get('status') != 'success':
        fail(f"color_temperature error: {r.get('error', '')}")
    results = r.get('results') or {}
    if results.get('kelvin') != 4000 or results.get('tint') != 5:
        fail(f"echo mismatch: {results!r}")

passed("color_temperature: 4000K tint=5 applied")
