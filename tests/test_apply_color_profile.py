#!/usr/bin/env python3
"""Live test: apply_color_profile reports 'file not found' for a bogus path.

Without shipping a real ICC blob, the endpoint is exercised via its
file-not-found fail path — still validates it dispatches and returns a
structured error.
"""
from tests._harness import cmd, fail, passed, canvas

with canvas() as idx:
    r = cmd('apply_color_profile', {
        'image_index': idx,
        'profile_path': r'C:\nonexistent\profile.icc',
        'intent': 'perceptual',
    })
if r.get('status') == 'success':
    fail(f"unexpected success: {r!r}")
err = r.get('error') or ''
if 'not found' not in err.lower() and 'no such file' not in err.lower():
    fail(f"unexpected error shape: {err[:140]}")

passed("apply_color_profile: reachable, 'file not found' for bogus path")
