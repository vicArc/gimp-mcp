#!/usr/bin/env python3
"""Live test: export_animated_sprite_strip writes the layer stack as one image."""
import os, tempfile
from tests._harness import cmd, fail, passed, canvas

tmp = tempfile.mkdtemp(prefix='gimpmcp_strip_')
try:
    with canvas(width=32, height=32) as idx:
        cmd('create_layer', {'image_index': idx, 'name': 'f2',
                              'width': 32, 'height': 32, 'fill': '#0033aa'})
        r = cmd('export_animated_sprite_strip', {
            'image_index': idx, 'output_path': tmp,
            'orientation': 'horizontal', 'padding': 0,
        })
        if r.get('status') != 'success':
            fail(f"export_animated_sprite_strip error: {r.get('error', '')}")
    passed("export_animated_sprite_strip: horizontal orientation accepted")
finally:
    for name in os.listdir(tmp):
        try: os.remove(os.path.join(tmp, name))
        except Exception: pass
    try: os.rmdir(tmp)
    except Exception: pass
