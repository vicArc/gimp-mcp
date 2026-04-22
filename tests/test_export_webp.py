#!/usr/bin/env python3
"""Live test: export_webp writes a WebP file."""
import os, tempfile
from tests._harness import cmd, fail, passed, canvas

tmp = tempfile.mkdtemp(prefix='gimpmcp_webp_')
path = os.path.join(tmp, 'out.webp')
try:
    with canvas() as idx:
        r = cmd('export_webp', {'image_index': idx, 'file_path': path, 'quality': 85})
        if r.get('status') != 'success':
            fail(f"export_webp error: {r.get('error', '')}")
        if not os.path.exists(path) or os.path.getsize(path) == 0:
            fail(f"WebP file not created or empty: {path}")
    passed(f"export_webp: {os.path.getsize(path)}B")
finally:
    try: os.remove(path)
    except Exception: pass
    try: os.rmdir(tmp)
    except Exception: pass
