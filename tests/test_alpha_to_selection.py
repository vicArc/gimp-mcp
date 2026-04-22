#!/usr/bin/env python3
"""Live test: alpha_to_selection loads the active layer's alpha as selection."""
from tests._harness import cmd, fail, passed, canvas

with canvas() as idx:
    r = cmd('alpha_to_selection', {'image_index': idx, 'operation': 'replace'})
    if r.get('status') != 'success':
        fail(f"alpha_to_selection error: {r.get('error', '')}")
    results = r.get('results') or {}
    if results.get('operation') != 'replace':
        fail(f"operation echo mismatch: {results!r}")

passed(f"alpha_to_selection: layer={results.get('layer_name')!r}")
