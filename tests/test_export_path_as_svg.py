#!/usr/bin/env python3
"""Live test: export_path_as_svg writes a path out as SVG."""
import os, tempfile
from tests._harness import cmd, fail, passed, canvas

tmp = tempfile.mkdtemp(prefix='gimpmcp_svg_out_')
path = os.path.join(tmp, 'out.svg')
try:
    with canvas() as idx:
        cmd('path_create', {
            'image_index': idx, 'name': '_test_pxsvg',
            'points': [{'anchor': [10, 10]}, {'anchor': [50, 50]}, {'anchor': [20, 40]}],
            'close': True,
        })
        r = cmd('export_path_as_svg', {
            'image_index': idx, 'path_name': '_test_pxsvg', 'file_path': path,
        })
        if r.get('status') != 'success':
            fail(f"export_path_as_svg error: {r.get('error', '')}")
        if not os.path.exists(path) or os.path.getsize(path) == 0:
            fail(f"SVG not created: {path}")
    passed(f"export_path_as_svg: {os.path.getsize(path)}B")
finally:
    try: os.remove(path)
    except Exception: pass
    try: os.rmdir(tmp)
    except Exception: pass
