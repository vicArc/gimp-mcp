#!/usr/bin/env python3
"""Live test: every plugin error response now carries the structured fields.

Triggers a known error (missing image) and confirms error_type /
error_message / error_code / traceback are present alongside the legacy
`error` field.
"""
from tests._harness import cmd, fail, passed

r = cmd('close_image', {'image_index': 99999, 'save_first': False})
if r.get('status') != 'error':
    fail(f"expected status=error, got: {r.get('status')!r}")
for key in ('error', 'error_type', 'error_message', 'error_code', 'traceback'):
    if key not in r:
        fail(f"missing structured key {key!r}: {sorted(r.keys())}")
if r.get('error') != r.get('error_message'):
    fail(f"error != error_message: {r!r}")

passed(f"structured_error: type={r.get('error_type')} msg={str(r.get('error'))[:60]}")
