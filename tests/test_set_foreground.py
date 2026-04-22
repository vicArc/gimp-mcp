#!/usr/bin/env python3
"""Live test: set_foreground accepts a color string."""
from tests._harness import cmd, fail, passed

r = cmd('set_foreground', {'color': '#ff8800'})
if r.get('status') != 'success':
    fail(f"set_foreground error: {r.get('error', '')}")
passed("set_foreground: #ff8800 accepted")
