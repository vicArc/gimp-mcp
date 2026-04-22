#!/usr/bin/env python3
"""Live test: run_pdb_procedure invokes an arbitrary PDB proc."""
from tests._harness import cmd, fail, passed

r = cmd('run_pdb_procedure', {
    'name': 'gimp-context-set-opacity',
    'args': {'opacity': 75.0},
})
if r.get('status') != 'success':
    fail(f"run_pdb_procedure error: {r.get('error', '')}")
applied = (r.get('results') or {}).get('applied') or []
if 'opacity' not in applied:
    fail(f"opacity not in applied: {applied!r}")

passed("run_pdb_procedure: gimp-context-set-opacity ran")
