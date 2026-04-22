#!/usr/bin/env python3
"""Live test: apply_bokeh returns the 'not available' stub on 3.2 core GEGL."""
from tests._harness import cmd, fail, passed

r = cmd('apply_bokeh', {'radius': 5.0})
if r.get('status') == 'success':
    passed("apply_bokeh: unexpectedly supported")
err = r.get('error') or ''
if 'not available' in err.lower() or 'gegl:bokeh' in err.lower() or 'apply_lens_blur' in err.lower():
    passed("apply_bokeh: structured not-available (expected)")
fail(f"unexpected error shape: {err[:140]}")
