#!/usr/bin/env python3
"""Live test: list_gegl_operations enumerates gegl:* ops."""
from tests._harness import cmd, fail, passed

r = cmd('list_gegl_operations', {'prefix': 'gegl:'})
if r.get('status') != 'success':
    fail(f"list_gegl_operations error: {r.get('error', '')}")
ops = (r.get('results') or {}).get('operations') or []
if not ops or 'gegl:gaussian-blur' not in ops:
    fail(f"gegl:gaussian-blur missing (got {len(ops)} ops)")

passed(f"list_gegl_operations: {len(ops)} ops, gegl:gaussian-blur present")
