#!/usr/bin/env python3
"""Live test: list_palettes returns string names for installed palettes."""
from tests._harness import cmd, fail, passed

r = cmd('list_palettes', {})
if r.get('status') != 'success':
    fail(f"list_palettes returned error: {r.get('error', '')}")

results = r.get('results') or {}
names = results.get('palettes') or []
count = results.get('count')

if not isinstance(names, list) or not names:
    fail(f"palettes list is empty or not a list: {names!r}")
if count != len(names):
    fail(f"count {count!r} != len(names) {len(names)}")
if not all(isinstance(n, str) for n in names):
    fail("non-string palette names present")

passed(f"list_palettes: {count} palettes")
