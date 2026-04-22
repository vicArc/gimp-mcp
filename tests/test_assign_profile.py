#!/usr/bin/env python3
"""Live test: assign_profile reports 'file not found' for a bogus path."""
from tests._harness import cmd, fail, passed, canvas

with canvas() as idx:
    r = cmd('assign_profile', {
        'image_index': idx,
        'profile_path': r'C:\nonexistent\profile.icc',
    })
if r.get('status') == 'success':
    fail(f"unexpected success: {r!r}")
err = r.get('error') or ''
if 'not found' not in err.lower() and 'no such file' not in err.lower():
    fail(f"unexpected error shape: {err[:140]}")

passed("assign_profile: reachable, 'file not found' for bogus path")
