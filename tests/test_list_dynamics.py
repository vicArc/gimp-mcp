#!/usr/bin/env python3
"""Live test: list_dynamics returns a list (may fall back to active dynamics only)."""
from tests._harness import cmd, fail, passed

r = cmd('list_dynamics', {})
if r.get('status') != 'success':
    fail(f"list_dynamics returned error: {r.get('error', '')}")

results = r.get('results') or {}
names = results.get('dynamics')
count = results.get('count')

if not isinstance(names, list):
    fail(f"dynamics is not a list: {names!r}")
if not isinstance(count, int):
    fail(f"count is not an int: {count!r}")

passed(f"list_dynamics: {count} entries (fallback is active-only)")
