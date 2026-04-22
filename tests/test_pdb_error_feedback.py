#!/usr/bin/env python3
"""Live test: PDB errors surface + return values forwarded.

Covers the two wins from the structured-error task:
1. run_pdb_procedure with a known-good proc returns return_values
2. run_pdb_procedure with a bad argument surfaces an error (not silent success)
"""
from tests._harness import cmd, fail, passed

# --- Test A: return values forwarded ---
r = cmd('run_pdb_procedure', {'name': 'gimp-version', 'args': {}})
if r.get('status') != 'success':
    fail(f"run_pdb_procedure(gimp-version) failed: {r.get('error', r)}")

results = r.get('results') or {}
ret = results.get('return_values')
if not ret:
    fail(f"return_values missing or empty for gimp-version: {results!r}")
version_str = ret[0] if isinstance(ret, list) and ret else None
if not version_str or not str(version_str).startswith('3'):
    fail(f"expected version string starting with '3', got {version_str!r}")

# --- Test B: missing proc surfaces error ---
r2 = cmd('run_pdb_procedure', {'name': 'gimp-nonexistent-proc-xyz', 'args': {}})
if r2.get('status') != 'error':
    fail(f"expected error for unknown proc, got status={r2.get('status')!r}")

# --- Test C: check_server via exec still works (smoke) ---
r3 = cmd('check_server', {})
if r3.get('status') != 'success':
    fail(f"check_server broken after changes: {r3}")

passed(f"PDB error feedback: gimp-version returned {version_str!r}, unknown proc errors correctly")
