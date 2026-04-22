#!/usr/bin/env python3
"""Live test: list_brushes returns the installed brush catalogue."""
from tests._harness import cmd, fail, passed

r = cmd('list_brushes', {})
if r.get('status') != 'success':
    fail(f"list_brushes returned error: {r.get('error', '')}")

results = r.get('results') or {}
names = results.get('brushes') or []
count = results.get('count')

if not isinstance(names, list) or not names:
    fail(f"brushes list is empty or not a list: {names!r}")
if count != len(names):
    fail(f"count {count!r} != len(names) {len(names)}")
if not all(isinstance(n, str) for n in names):
    non_str = [n for n in names if not isinstance(n, str)][:3]
    fail(f"non-string names present (3.x object leak?): {non_str!r}")

passed(f"list_brushes: {count} brushes, all string names")
