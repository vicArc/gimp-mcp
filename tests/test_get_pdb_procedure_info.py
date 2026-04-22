#!/usr/bin/env python3
"""Live test: get_pdb_procedure_info surfaces a real procedure's metadata."""
from tests._harness import cmd, fail, passed

r = cmd('get_pdb_procedure_info', {'name': 'gimp-drawable-hue-saturation'})
if r.get('status') != 'success':
    fail(f"get_pdb_procedure_info error: {r.get('error', '')}")
args = (r.get('results') or {}).get('arguments') or []
names = {a.get('name') for a in args}
if 'overlap' not in names:
    fail(f"expected 'overlap' arg on 3.2 signature: {sorted(names)}")

passed(f"get_pdb_procedure_info: hue-saturation has {len(args)} args incl. 'overlap'")
