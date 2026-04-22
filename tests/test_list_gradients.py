#!/usr/bin/env python3
"""Live test: list_gradients returns string names for installed gradients."""
from tests._harness import cmd, fail, passed

r = cmd('list_gradients', {})
if r.get('status') != 'success':
    fail(f"list_gradients returned error: {r.get('error', '')}")

results = r.get('results') or {}
names = results.get('gradients') or []
count = results.get('count')

if not isinstance(names, list) or not names:
    fail(f"gradients list is empty or not a list: {names!r}")
if count != len(names):
    fail(f"count {count!r} != len(names) {len(names)}")
if not all(isinstance(n, str) for n in names):
    fail("non-string gradient names present")

passed(f"list_gradients: {count} gradients")
