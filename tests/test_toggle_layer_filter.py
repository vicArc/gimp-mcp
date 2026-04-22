#!/usr/bin/env python3
"""Live test: toggle_layer_filter flips a live filter's visibility."""
from tests._harness import cmd, fail, passed, canvas

with canvas() as idx:
    a = cmd('apply_filter_nondestructive', {
        'image_index': idx, 'operation': 'gegl:gaussian-blur',
        'properties': {'std-dev-x': 1.0, 'std-dev-y': 1.0},
    })
    fid = (a.get('results') or {}).get('filter_id')
    r = cmd('toggle_layer_filter', {
        'image_index': idx, 'filter_id': fid, 'visible': False,
    })
    if r.get('status') != 'success':
        fail(f"toggle_layer_filter error: {r.get('error', '')}")
    if (r.get('results') or {}).get('visible') is not False:
        fail(f"visible not False: {r!r}")

passed(f"toggle_layer_filter: filter_id={fid} hidden")
