#!/usr/bin/env python3
"""Live test: get_current_profile reports the image's ICC status."""
from tests._harness import cmd, fail, passed, canvas

with canvas() as idx:
    r = cmd('get_current_profile', {'image_index': idx})
    if r.get('status') != 'success':
        fail(f"get_current_profile error: {r.get('error', '')}")
    results = r.get('results') or {}
    if 'has_profile' not in results:
        fail(f"has_profile missing: {results!r}")

passed(f"get_current_profile: has_profile={results.get('has_profile')}")
