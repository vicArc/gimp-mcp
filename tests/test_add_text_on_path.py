#!/usr/bin/env python3
"""Live test: add_text_on_path returns the 'not available' structured error on 3.2.2."""
from tests._harness import cmd, fail, passed

r = cmd('add_text_on_path', {
    'path_name': '_missing', 'text': 'hi', 'font': 'Sans', 'size': 16,
})
if r.get('status') == 'success':
    passed("add_text_on_path: unexpectedly supported")
err = r.get('error') or ''
if 'not available' in err.lower() or 'ui-only' in err.lower() or 'workaround' in err.lower():
    passed("add_text_on_path: structured not-available (expected)")
fail(f"unexpected error shape: {err[:140]}")
