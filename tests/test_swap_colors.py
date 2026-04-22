#!/usr/bin/env python3
"""Live test: swap_colors succeeds with no args."""
from tests._harness import cmd, fail, passed

r = cmd('swap_colors', {})
if r.get('status') != 'success':
    fail(f"swap_colors error: {r.get('error', '')}")
passed("swap_colors: ok")
