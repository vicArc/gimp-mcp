#!/usr/bin/env python3
"""Live test: apply_filter runs a generic gegl:* op destructively."""
from tests._harness import cmd, fail, passed, canvas

with canvas() as idx:
    r = cmd('apply_filter', {
        'image_index': idx, 'operation': 'gegl:gaussian-blur',
        'properties': {'std-dev-x': 2.0, 'std-dev-y': 2.0},
    })
    if r.get('status') != 'success':
        fail(f"apply_filter error: {r.get('error', '')}")
    if (r.get('results') or {}).get('operation') != 'gegl:gaussian-blur':
        fail(f"operation echo mismatch: {r!r}")

passed("apply_filter: gegl:gaussian-blur applied")
