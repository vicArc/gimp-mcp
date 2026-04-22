#!/usr/bin/env python3
"""Live test: update_layer_filter re-tunes a live filter's props."""
from tests._harness import cmd, fail, passed, canvas

with canvas() as idx:
    a = cmd('apply_filter_nondestructive', {
        'image_index': idx, 'operation': 'gegl:gaussian-blur',
        'properties': {'std-dev-x': 1.0, 'std-dev-y': 1.0},
    })
    fid = (a.get('results') or {}).get('filter_id')
    if fid is None:
        fail(f"could not create filter: {a!r}")
    r = cmd('update_layer_filter', {
        'image_index': idx, 'filter_id': fid,
        'properties': {'std-dev-x': 4.0, 'std-dev-y': 4.0},
    })
    if r.get('status') != 'success':
        fail(f"update_layer_filter error: {r.get('error', '')}")
    if 'std-dev-x' not in ((r.get('results') or {}).get('applied') or []):
        fail(f"std-dev-x not applied: {r!r}")

passed(f"update_layer_filter: filter_id={fid} updated")
