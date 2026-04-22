#!/usr/bin/env python3
"""Live test: save_workspace writes XCF + manifest for open images."""
import os, tempfile
from tests._harness import cmd, fail, passed, canvas

tmp = tempfile.mkdtemp(prefix='gimpmcp_ws_')
try:
    with canvas():
        r = cmd('save_workspace', {'path': tmp})
        if r.get('status') != 'success':
            fail(f"save_workspace error: {r.get('error', '')}")
        manifest = (r.get('results') or {}).get('manifest')
        if not manifest or not os.path.exists(manifest):
            fail(f"manifest missing: {r!r}")
    passed(f"save_workspace: manifest={manifest}")
finally:
    for name in os.listdir(tmp):
        try: os.remove(os.path.join(tmp, name))
        except Exception: pass
    try: os.rmdir(tmp)
    except Exception: pass
