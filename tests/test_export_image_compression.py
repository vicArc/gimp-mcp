#!/usr/bin/env python3
"""Live test: export_image honors the new png_compression / jpeg_subsample knobs."""
import os, tempfile
from tests._harness import cmd, fail, passed, canvas

tmp = tempfile.mkdtemp(prefix='gimpmcp_expknobs_')
png = os.path.join(tmp, 'out.png')
jpg = os.path.join(tmp, 'out.jpg')
try:
    with canvas() as idx:
        r1 = cmd('export_image', {
            'image_index': idx, 'file_path': png,
            'format': 'png', 'png_compression': 9,
        })
        if r1.get('status') != 'success':
            fail(f"export_image png error: {r1.get('error', '')}")
        r2 = cmd('export_image', {
            'image_index': idx, 'file_path': jpg,
            'format': 'jpeg', 'quality': 80, 'jpeg_subsample': 2,
        })
        if r2.get('status') != 'success':
            fail(f"export_image jpeg error: {r2.get('error', '')}")
    passed(f"export_image knobs: png={os.path.getsize(png)}B jpeg={os.path.getsize(jpg)}B")
finally:
    for p in (png, jpg):
        try: os.remove(p)
        except Exception: pass
    try: os.rmdir(tmp)
    except Exception: pass
