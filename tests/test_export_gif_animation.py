#!/usr/bin/env python3
"""Live test: export_gif_animation writes an animated GIF from layer frames."""
import os, tempfile
from tests._harness import cmd, fail, passed, canvas

tmp = tempfile.mkdtemp(prefix='gimpmcp_gif_')
path = os.path.join(tmp, 'anim.gif')
try:
    with canvas(width=40, height=40) as idx:
        cmd('create_layer', {'image_index': idx, 'name': 'frame2',
                              'width': 40, 'height': 40, 'fill': '#ff0000'})
        cmd('create_layer', {'image_index': idx, 'name': 'frame3',
                              'width': 40, 'height': 40, 'fill': '#00ff00'})
        r = cmd('export_gif_animation', {
            'image_index': idx, 'file_path': path,
            'delay_ms': 120, 'loop_count': 0, 'dither': True,
        })
        if r.get('status') != 'success':
            fail(f"export_gif_animation error: {r.get('error', '')}")
        if not os.path.exists(path) or os.path.getsize(path) == 0:
            fail(f"GIF not created: {path}")
    passed(f"export_gif_animation: {os.path.getsize(path)}B")
finally:
    try: os.remove(path)
    except Exception: pass
    try: os.rmdir(tmp)
    except Exception: pass
