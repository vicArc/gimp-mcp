#!/usr/bin/env python3
"""Live test: rollback_transaction undoes everything in the group."""
from tests._harness import cmd, fail, passed, canvas

with canvas() as idx:
    cmd('begin_transaction', {'image_index': idx, 'name': '_test_rt'})
    cmd('posterize', {'image_index': idx, 'levels': 3})
    r = cmd('rollback_transaction', {'name': '_test_rt'})
    if r.get('status') != 'success':
        fail(f"rollback_transaction error: {r.get('error', '')}")
    if (r.get('results') or {}).get('rolled_back') is not True:
        fail(f"rolled_back not True: {r!r}")

passed("rollback_transaction: rolled back")
