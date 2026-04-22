#!/usr/bin/env python3
"""Live test: list_channels returns a list (may be empty on fresh canvas)."""
from tests._harness import cmd, fail, passed, canvas

with canvas() as idx:
    r = cmd('list_channels', {'image_index': idx})
    if r.get('status') != 'success':
        fail(f"list_channels error: {r.get('error', '')}")
    results = r.get('results') or {}
    if not isinstance(results.get('channels'), list):
        fail(f"channels not a list: {results!r}")

passed(f"list_channels: count={results.get('count')}")
