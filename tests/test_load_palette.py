#!/usr/bin/env python3
"""Live test: load_palette parses a .gpl text file."""
import os, tempfile
from tests._harness import cmd, fail, passed

gpl = """GIMP Palette
Name: _test_loadpal
Columns: 0
#
  0   0   0\tBlack
255 255 255\tWhite
255   0   0\tRed
  0 255   0\tGreen
  0   0 255\tBlue
"""
tmp = tempfile.mkdtemp(prefix='gimpmcp_gpl_')
path = os.path.join(tmp, 'tpal.gpl')
try:
    with open(path, 'w') as f:
        f.write(gpl)
    r = cmd('load_palette', {'file_path': path})
    if r.get('status') != 'success':
        fail(f"load_palette error: {r.get('error', '')}")
    results = r.get('results') or {}
    if results.get('entries') != 5:
        fail(f"entries count mismatch: {results!r}")
    passed(f"load_palette: {results.get('palette_name')!r} entries={results.get('entries')}")
finally:
    try: os.remove(path)
    except Exception: pass
    try: os.rmdir(tmp)
    except Exception: pass
