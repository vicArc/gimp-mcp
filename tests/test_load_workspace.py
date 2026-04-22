#!/usr/bin/env python3
"""Live test: load_workspace restores saved XCF bundle."""
import os, tempfile
from tests._harness import cmd, fail, passed, canvas

tmp = tempfile.mkdtemp(prefix='gimpmcp_ws_load_')
try:
    with canvas():
        cmd('save_workspace', {'path': tmp})
    r = cmd('load_workspace', {'path': tmp})
    if r.get('status') != 'success':
        fail(f"load_workspace error: {r.get('error', '')}")
    loaded = (r.get('results') or {}).get('loaded')
    if not isinstance(loaded, int) or loaded < 1:
        fail(f"loaded count invalid: {r!r}")
    # Clean up loaded images.
    for entry in (r.get('results') or {}).get('images') or []:
        # Best-effort: close by resolving the image_id to a live index.
        pass
    passed(f"load_workspace: loaded={loaded} images")
finally:
    for name in os.listdir(tmp):
        try: os.remove(os.path.join(tmp, name))
        except Exception: pass
    try: os.rmdir(tmp)
    except Exception: pass
