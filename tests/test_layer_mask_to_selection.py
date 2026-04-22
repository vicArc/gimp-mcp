#!/usr/bin/env python3
"""Live test: layer_mask_to_selection loads mask as selection."""
from tests._harness import cmd, fail, passed, canvas

with canvas() as idx:
    cmd('add_layer_mask', {'image_index': idx, 'mask_type': 'white'})
    r = cmd('layer_mask_to_selection', {'image_index': idx, 'operation': 'replace'})
    if r.get('status') != 'success':
        fail(f"layer_mask_to_selection error: {r.get('error', '')}")

passed("layer_mask_to_selection: applied")
