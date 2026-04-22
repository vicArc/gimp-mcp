#!/usr/bin/env python3
"""Live test: import_svg_as_path loads an SVG as one or more paths."""
import os, tempfile
from tests._harness import cmd, fail, passed, canvas

svg = '''<?xml version="1.0"?>
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 100" width="100" height="100">
  <path d="M10 10 L 90 10 L 90 90 L 10 90 Z"/>
</svg>'''
tmp = tempfile.mkdtemp(prefix='gimpmcp_svg_')
path = os.path.join(tmp, 'square.svg')
try:
    with open(path, 'w') as f:
        f.write(svg)
    with canvas() as idx:
        r = cmd('import_svg_as_path', {
            'image_index': idx, 'file_path': path,
            'merge': True, 'scale': True,
        })
        if r.get('status') != 'success':
            fail(f"import_svg_as_path error: {r.get('error', '')}")
        imported = (r.get('results') or {}).get('imported') or []
        if not imported:
            fail(f"no paths imported: {r!r}")
    passed(f"import_svg_as_path: {len(imported)} paths imported")
finally:
    try: os.remove(path)
    except Exception: pass
    try: os.rmdir(tmp)
    except Exception: pass
