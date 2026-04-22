#!/usr/bin/env python3
"""Live test: save_selection_as_channel saves the current selection."""
from tests._harness import cmd, fail, passed, canvas

with canvas() as idx:
    cmd('select_all', {'image_index': idx})
    r = cmd('save_selection_as_channel', {
        'image_index': idx, 'name': '_test_channel',
    })
    if r.get('status') != 'success':
        fail(f"save_selection_as_channel error: {r.get('error', '')}")
    results = r.get('results') or {}
    if results.get('name') != '_test_channel':
        fail(f"name echo mismatch: {results!r}")

passed(f"save_selection_as_channel: id={results.get('id')}")
