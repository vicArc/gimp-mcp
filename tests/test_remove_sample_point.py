#!/usr/bin/env python3
"""Live test: remove_sample_point deletes a sample point by id."""
from tests._harness import cmd, fail, passed, canvas

with canvas() as idx:
    a = cmd('add_sample_point', {'image_index': idx, 'x': 20, 'y': 20})
    spid = (a.get('results') or {}).get('sample_point_id')
    r = cmd('remove_sample_point', {'image_index': idx, 'sample_point_id': spid})
    if r.get('status') != 'success':
        fail(f"remove_sample_point error: {r.get('error', '')}")

passed(f"remove_sample_point: id={spid} removed")
