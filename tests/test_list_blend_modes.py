#!/usr/bin/env python3
"""Live test: list_blend_modes returns the blend-mode catalogue."""
from tests._harness import cmd, fail, passed

r = cmd('list_blend_modes')
if r.get('status') != 'success':
    fail(f"list_blend_modes returned error: {r.get('error', '')}")

results = r.get('results') or {}
modes = results.get('modes') or []
if not isinstance(modes, list) or not modes:
    fail(f"modes list is empty or not a list: {modes!r}")

keys = {m.get('key') for m in modes if isinstance(m, dict)}
for expected in ('NORMAL', 'MULTIPLY', 'GRAIN_MERGE', 'HSL_COLOR'):
    if expected not in keys:
        fail(f"expected mode key {expected!r} missing from {sorted(keys)[:10]}")

passed(f"list_blend_modes: {len(modes)} modes, GRAIN_MERGE + HSL_COLOR present")
