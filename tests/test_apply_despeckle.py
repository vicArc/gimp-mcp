#!/usr/bin/env python3
"""Live test: apply_despeckle wraps gegl:noise-reduction."""
from tests._harness import cmd, fail, passed, canvas

with canvas() as idx:
    r = cmd('apply_despeckle', {'image_index': idx, 'radius': 2})
    if r.get('status') != 'success':
        fail(f"apply_despeckle error: {r.get('error', '')}")

passed("apply_despeckle: radius=2 (iterations=2) applied")
