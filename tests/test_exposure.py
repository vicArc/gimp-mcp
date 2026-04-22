#!/usr/bin/env python3
"""Live test: exposure applies gegl:exposure."""
from tests._harness import cmd, fail, passed, canvas

with canvas() as idx:
    r = cmd('exposure', {'image_index': idx, 'ev_stops': 0.5, 'black_level': 0.0})
    if r.get('status') != 'success':
        fail(f"exposure error: {r.get('error', '')}")
    if (r.get('results') or {}).get('ev_stops') != 0.5:
        fail(f"echo mismatch: {r!r}")

passed("exposure: +0.5 stops applied")
