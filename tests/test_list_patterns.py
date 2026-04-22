#!/usr/bin/env python3
"""Live test: list_patterns returns string names for installed patterns."""
from tests._harness import cmd, fail, passed

r = cmd('list_patterns', {})
if r.get('status') != 'success':
    fail(f"list_patterns returned error: {r.get('error', '')}")

results = r.get('results') or {}
names = results.get('patterns') or []
count = results.get('count')

if not isinstance(names, list) or not names:
    fail(f"patterns list is empty or not a list: {names!r}")
if count != len(names):
    fail(f"count {count!r} != len(names) {len(names)}")
if not all(isinstance(n, str) for n in names):
    fail("non-string pattern names present")

passed(f"list_patterns: {count} patterns")
