#!/usr/bin/env python3
"""Live test: import_psd round-trips with export_psd."""
import os, tempfile
from tests._harness import cmd, fail, passed, canvas

tmp = tempfile.mkdtemp(prefix='gimpmcp_psd_in_')
path = os.path.join(tmp, 'round.psd')
try:
    with canvas() as idx:
        cmd('export_psd', {'image_index': idx, 'file_path': path})
    r = cmd('import_psd', {'file_path': path})
    if r.get('status') != 'success':
        fail(f"import_psd error: {r.get('error', '')}")
    results = r.get('results') or {}
    new_idx = results.get('image_index')
    new_id  = results.get('image_id')
    if not isinstance(new_id, int) or new_id <= 0:
        fail(f"image_id invalid: {results!r}")
    # Resolve the imported image's current index for cleanup.
    li = cmd('list_images', {})
    images = (li.get('results') or {}).get('images') or []
    for i, info in enumerate(images):
        if isinstance(info, dict) and info.get('image_id') == new_id:
            cmd('close_image', {'image_index': i, 'save_first': False})
            break
    passed(f"import_psd: image_id={new_id}")
finally:
    try: os.remove(path)
    except Exception: pass
    try: os.rmdir(tmp)
    except Exception: pass
