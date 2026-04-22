#!/usr/bin/env python3
"""Live test: remove_layer_filter deletes a live filter."""
from tests._harness import cmd, fail, passed, canvas

with canvas() as idx:
    a = cmd('apply_filter_nondestructive', {
        'image_index': idx, 'operation': 'gegl:gaussian-blur',
        'properties': {'std-dev-x': 1.0, 'std-dev-y': 1.0},
    })
    fid = (a.get('results') or {}).get('filter_id')
    r = cmd('remove_layer_filter', {'image_index': idx, 'filter_id': fid})
    if r.get('status') != 'success':
        fail(f"remove_layer_filter error: {r.get('error', '')}")

passed(f"remove_layer_filter: filter_id={fid} removed")
