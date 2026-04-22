#!/usr/bin/env python3
"""Live test: commit_transaction closes an active undo group."""
from tests._harness import cmd, fail, passed, canvas

with canvas() as idx:
    cmd('begin_transaction', {'image_index': idx, 'name': '_test_ct'})
    r = cmd('commit_transaction', {'name': '_test_ct'})
    if r.get('status') != 'success':
        fail(f"commit_transaction error: {r.get('error', '')}")

passed("commit_transaction: closed")
