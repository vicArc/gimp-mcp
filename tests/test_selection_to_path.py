#!/usr/bin/env python3
"""Live test: selection_to_path returns a structured 'not available' on 3.2.2.

The underlying plug-in-sel2path proc exists, but its `drawables` property
is typed GimpCoreObjectArray which PyGObject in 3.2.2 can't marshal from
a Python list. Until the binding gap closes, the tool surfaces a clear
error instead of a cryptic GObject conversion failure.
"""
from tests._harness import cmd, fail, passed, canvas

with canvas() as idx:
    cmd('select_rectangle', {'image_index': idx, 'x': 20, 'y': 20, 'width': 40, 'height': 30})
    r = cmd('selection_to_path', {'image_index': idx})

if r.get('status') == 'success':
    passed("selection_to_path: unexpectedly supported")
err = r.get('error') or ''
if ('not available' in err.lower()
        or 'gimpcoreobjectarray' in err.lower()
        or 'path_create' in err.lower()):
    passed("selection_to_path: structured not-available (3.2.2 binding gap)")
fail(f"unexpected error shape: {err[:140]}")
