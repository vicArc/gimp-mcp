#!/usr/bin/env python3
"""Live test: get_palette_color reads a named palette entry by index."""
from tests._harness import cmd, fail, passed

# Ensure a known palette exists.
cmd('save_palette', {
    'name': '_test_getcolor_palette',
    'colors': ['#abcdef', '#010203'],
})
r = cmd('get_palette_color', {'name': '_test_getcolor_palette', 'index': 1})
if r.get('status') != 'success':
    fail(f"get_palette_color error: {r.get('error', '')}")
results = r.get('results') or {}
if results.get('index') != 1 or not results.get('hex'):
    fail(f"unexpected result: {results!r}")
passed(f"get_palette_color: index=1 hex={results.get('hex')}")
