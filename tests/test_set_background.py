#!/usr/bin/env python3
"""Live test: set_background accepts a color string."""
from tests._harness import cmd, fail, passed

r = cmd('set_background', {'color': '#0088ff'})
if r.get('status') != 'success':
    fail(f"set_background error: {r.get('error', '')}")
passed("set_background: #0088ff accepted")
