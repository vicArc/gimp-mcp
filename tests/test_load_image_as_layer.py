#!/usr/bin/env python3
"""Live test: load_image_as_layer imports an external image."""
import os, tempfile
from tests._harness import cmd, fail, passed, canvas

tmp = tempfile.mkdtemp(prefix='gimpmcp_loadlayer_')
png = os.path.join(tmp, 'src.png')
try:
    with canvas() as src_idx:
        cmd('fill_layer', {'image_index': src_idx, 'color': '#ff00aa'})
        cmd('export_image', {'image_index': src_idx, 'file_path': png, 'format': 'png'})
    with canvas() as idx:
        r = cmd('load_image_as_layer', {
            'image_index': idx, 'file_path': png,
            'layer_name': '_test_imported', 'fit_canvas': True,
        })
        if r.get('status') != 'success':
            fail(f"load_image_as_layer error: {r.get('error', '')}")
        if (r.get('results') or {}).get('layer_name') != '_test_imported':
            fail(f"layer_name mismatch: {r!r}")
    passed("load_image_as_layer: imported + fit to canvas")
finally:
    try: os.remove(png)
    except Exception: pass
    try: os.rmdir(tmp)
    except Exception: pass
