#!/usr/bin/env python3
"""Live test: export_tiff writes a TIFF file."""
import os, tempfile
from tests._harness import cmd, fail, passed, canvas

tmp = tempfile.mkdtemp(prefix='gimpmcp_tiff_')
path = os.path.join(tmp, 'out.tif')
try:
    with canvas() as idx:
        r = cmd('export_tiff', {'image_index': idx, 'file_path': path, 'compression': 'lzw'})
        if r.get('status') != 'success':
            fail(f"export_tiff error: {r.get('error', '')}")
        if not os.path.exists(path) or os.path.getsize(path) == 0:
            fail(f"TIFF not created: {path}")
    passed(f"export_tiff: {os.path.getsize(path)}B")
finally:
    try: os.remove(path)
    except Exception: pass
    try: os.rmdir(tmp)
    except Exception: pass
