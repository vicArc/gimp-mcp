#!/usr/bin/env python3
"""Live test: export_hdr writes a Radiance HDR file."""
import os, tempfile
from tests._harness import cmd, fail, passed, canvas

tmp = tempfile.mkdtemp(prefix='gimpmcp_hdr_')
path = os.path.join(tmp, 'out.hdr')
try:
    with canvas() as idx:
        r = cmd('export_hdr', {'image_index': idx, 'file_path': path})
        if r.get('status') != 'success':
            fail(f"export_hdr error: {r.get('error', '')}")
        if not os.path.exists(path) or os.path.getsize(path) == 0:
            fail(f"HDR not created: {path}")
    passed(f"export_hdr: {os.path.getsize(path)}B")
finally:
    try: os.remove(path)
    except Exception: pass
    try: os.rmdir(tmp)
    except Exception: pass
