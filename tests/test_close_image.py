#!/usr/bin/env python3
"""Live test: close_image doesn't crash on GIMP 3.2 (Bug #3 regression)."""
from tests._harness import cmd, fail, passed

# Create a fresh canvas and close it — don't use the canvas() context manager
# because that calls close_image internally (testing the fixer there too)
r = cmd('new_canvas', {'width': 50, 'height': 50, 'fill': 'white', 'name': 'close_test'})
if r.get('status') != 'success':
    fail(f"new_canvas failed: {r.get('error', '')}")

image_id = (r.get('results') or {}).get('image_id')
li = cmd('list_images', {})
images = (li.get('results') or {}).get('images') or []
idx = next((i for i, info in enumerate(images)
            if isinstance(info, dict) and info.get('image_id') == image_id), None)
if idx is None:
    fail(f"could not find new canvas image_id={image_id} in list_images")

r2 = cmd('close_image', {'image_index': idx, 'save_first': False})
if r2.get('status') != 'success':
    fail(f"close_image failed: {r2.get('error', r2)}")

passed("close_image: completed without crash")
