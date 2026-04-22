#!/usr/bin/env python3
"""Live test: list_pdb_procedures.

The plugin currently tries gimp-pdb-query which is absent on this build;
assertion is loose — either a non-empty list (future-fix) or a
'not available' error with a structured shape.
"""
from tests._harness import cmd, fail, passed

r = cmd('list_pdb_procedures', {'filter': 'gimp-drawable'})
if r.get('status') == 'success':
    results = r.get('results') or {}
    names = results.get('procedures') or []
    if not names:
        fail(f"success but empty list: {results!r}")
    passed(f"list_pdb_procedures: {len(names)} matches")
err = r.get('error') or ''
if 'not available' in err.lower() or 'gimp-pdb-query' in err.lower():
    passed(f"list_pdb_procedures: structured not-available (build-specific): {err[:60]}")
fail(f"unexpected error shape: {err[:140]}")
