#!/usr/bin/env python3
"""Live test: begin_transaction opens a named undo group."""
from tests._harness import cmd, fail, passed, canvas

with canvas() as idx:
    r = cmd('begin_transaction', {'image_index': idx, 'name': '_test_bt_open'})
    if r.get('status') != 'success':
        fail(f"begin_transaction error: {r.get('error', '')}")
    cmd('commit_transaction', {'name': '_test_bt_open'})

passed("begin_transaction: opened + committed")
