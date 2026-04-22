#!/usr/bin/env python3
"""Live test: copy_selection_to_clipboard copies the active drawable selection."""
from tests._harness import cmd, fail, passed, canvas

with canvas() as idx:
    cmd('select_rectangle', {'image_index': idx, 'x': 5, 'y': 5, 'width': 30, 'height': 20})
    r = cmd('copy_selection_to_clipboard', {'image_index': idx})
    if r.get('status') != 'success':
        fail(f"copy_selection_to_clipboard error: {r.get('error', '')}")

passed("copy_selection_to_clipboard: region copied")
