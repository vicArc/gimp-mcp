#!/usr/bin/env python3
"""Live test: get_gimp_info returns version + PDB capability info."""
from tests._harness import cmd, fail, passed

r = cmd('get_gimp_info')
if r.get('status') != 'success':
    fail(f"get_gimp_info returned error: {r.get('error', '')}")

results = r.get('results') or {}
for key in ('version', 'capabilities'):
    if key not in results:
        fail(f"missing {key!r} in results: {sorted(results.keys())[:8]}")

passed(f"get_gimp_info: version={results.get('version')!r}")
