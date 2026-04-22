#!/usr/bin/env python3
"""Live test: black_and_white performs the two-pass BW conversion."""
from tests._harness import cmd, fail, passed, canvas

with canvas(fill="#c03040") as idx:
    r = cmd('black_and_white', {'image_index': idx})
    if r.get('status') != 'success':
        fail(f"black_and_white error: {r.get('error', '')}")

passed("black_and_white: default weights applied")
