#!/usr/bin/env python3
"""Live test: export_exr writes an OpenEXR file."""
import os, tempfile
from tests._harness import cmd, fail, passed, canvas

tmp = tempfile.mkdtemp(prefix='gimpmcp_exr_')
path = os.path.join(tmp, 'out.exr')
try:
    with canvas() as idx:
        r = cmd('export_exr', {'image_index': idx, 'file_path': path})
        if r.get('status') != 'success':
            fail(f"export_exr error: {r.get('error', '')}")
        if not os.path.exists(path) or os.path.getsize(path) == 0:
            fail(f"EXR not created: {path}")
    passed(f"export_exr: {os.path.getsize(path)}B")
finally:
    try: os.remove(path)
    except Exception: pass
    try: os.rmdir(tmp)
    except Exception: pass
