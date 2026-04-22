#!/usr/bin/env python3
"""Live test: export_image with flatten=true produces correct output (not solid black)."""
import os, tempfile
from tests._harness import cmd, fail, passed, canvas

tmp = tempfile.mktemp(suffix='.png')
size = 0
try:
    with canvas(width=100, height=100, fill='white') as idx:
        cmd('fill_rectangle', {'image_index': idx, 'x': 20, 'y': 20,
                               'width': 60, 'height': 60, 'color': '#cc4400'})
        r = cmd('export_image', {
            'image_index': idx, 'file_path': tmp,
            'format': 'png', 'flatten': True,
        })
        if r.get('status') != 'success':
            fail(f"export_image(flatten=True) failed: {r.get('error', r)}")
        if not os.path.exists(tmp):
            fail("export produced no file")
        size = os.path.getsize(tmp)
        if size < 500:
            fail(f"PNG is suspiciously small ({size} bytes) — likely solid black")
finally:
    try: os.unlink(tmp)
    except Exception: pass

passed(f"export_image flatten=True: produced {size}-byte PNG with content")
