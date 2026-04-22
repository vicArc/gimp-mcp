#!/usr/bin/env python3
"""Live test: run_script_fu returns the expression result (Bug regression)."""
from tests._harness import cmd, fail, passed

r = cmd('run_script_fu', {'script': '(+ 1 2)'})
if r.get('status') != 'success':
    fail(f"run_script_fu error: {r.get('error', r)}")

results = r.get('results') or {}
result = results.get('result')
if result is None:
    fail(f"result is null — Script-Fu return value not captured: {results!r}")
if str(result).strip() != '3':
    fail(f"expected result='3', got {result!r}")

# Also verify gimp-version returns a string
r2 = cmd('run_script_fu', {'script': '(car (gimp-version))'})
if r2.get('status') != 'success':
    fail(f"gimp-version script failed: {r2.get('error', r2)}")
ver = (r2.get('results') or {}).get('result')
if not ver or not str(ver).startswith('3'):
    fail(f"expected version string starting with 3, got {ver!r}")

passed(f"run_script_fu: (+ 1 2)={result!r}, gimp-version={ver!r}")
