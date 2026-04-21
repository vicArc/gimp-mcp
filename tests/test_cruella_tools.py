#!/usr/bin/env python3
"""Smoke tests for the 3.2 migration helper endpoints.

Covers apply_filter, get_pdb_procedure_info, and list_gegl_operations.
Requires the GIMP MCP plugin running on localhost:9877.
Exits 0 on pass, 1 on fail.
"""
import json
import socket
import sys

HOST, PORT = '127.0.0.1', 9877


# ── transport ─────────────────────────────────────────────────────────────

def send(msg, timeout=30):
    """Send one JSON message to the MCP socket and return the reply."""
    s = socket.socket()
    s.settimeout(timeout)
    s.connect((HOST, PORT))
    s.send(json.dumps(msg).encode() + b'\n')
    buf = b''
    while True:
        try:
            chunk = s.recv(65536)
            if not chunk:
                break
            buf += chunk
            try:
                json.loads(buf.decode())
                break
            except json.JSONDecodeError:
                continue
        except socket.timeout:
            break
    s.close()
    try:
        return json.loads(buf.decode().strip())
    except json.JSONDecodeError:
        return {'status': 'error', 'error': 'parse: ' + buf.decode()[:200]}


def cmd(t, params=None):
    """Send a {type, params} command."""
    return send({'type': t, 'params': params or {}})


def fail(msg):
    """Abort with a failure banner on stderr."""
    print(f"FAIL: {msg}", file=sys.stderr)
    sys.exit(1)


# ── test steps ────────────────────────────────────────────────────────────

def test_list_gegl_operations():
    """list_gegl_operations must return a non-empty gegl:* list."""
    print("Testing list_gegl_operations(prefix='gegl:')...")
    r = cmd('list_gegl_operations', {'prefix': 'gegl:'})
    if r.get('status') != 'success':
        fail(f"list_gegl_operations failed: {r.get('error', '')}")
    results = r.get('results') or {}
    ops     = results.get('operations') or []
    count   = results.get('count')
    if not isinstance(ops, list) or not ops:
        fail(f"expected non-empty op list, got: {ops!r}")
    if count != len(ops):
        fail(f"count mismatch: count={count} len(ops)={len(ops)}")
    if not all(o.startswith('gegl:') for o in ops):
        fail(f"prefix filter broken — at least one op missing 'gegl:' prefix: {ops[:5]}")
    # Sanity-check a canonical op is present.
    if 'gegl:gaussian-blur' not in ops:
        fail(f"gegl:gaussian-blur missing from op list (got {len(ops)} ops, sample: {ops[:5]})")
    print(f"PASS list_gegl_operations: {count} ops, includes gegl:gaussian-blur")


def test_get_pdb_procedure_info():
    """get_pdb_procedure_info must surface the real 6-arg hue_saturation signature."""
    name = 'gimp-drawable-hue-saturation'
    print(f"Testing get_pdb_procedure_info({name!r})...")
    r = cmd('get_pdb_procedure_info', {'name': name})
    if r.get('status') != 'success':
        fail(f"get_pdb_procedure_info failed: {r.get('error', '')}")
    results = r.get('results') or {}
    args    = results.get('arguments') or []
    if not args:
        fail(f"no arguments reported for {name}: {results}")
    arg_names = {a.get('name') for a in args}
    # The 3.2 signature must expose 'overlap' — the property that was added and that
    # caused 5-arg calls to crash.
    if 'overlap' not in arg_names:
        fail(f"'overlap' arg missing — 3.2 migration regression? got: {sorted(arg_names)}")
    print(f"PASS get_pdb_procedure_info: {len(args)} args, 'overlap' present")


def test_apply_filter():
    """apply_filter must run a gegl:* op against a real canvas without error."""
    print("Creating 50x50 canvas for apply_filter test...")
    r = cmd('new_canvas', {'width': 50, 'height': 50, 'fill': 'white'})
    if r.get('status') != 'success':
        fail(f"new_canvas failed: {r.get('error', '')}")
    image_id = r.get('image_id') or (r.get('results') or {}).get('image_id')

    # Find the index for the image we just created so close_image is authoritative.
    li     = cmd('list_images', {})
    images = (li.get('results') or {}).get('images') or []
    target_index = 0
    for i, info in enumerate(images):
        if isinstance(info, dict) and info.get('image_id') == image_id:
            target_index = i
            break

    try:
        print("Calling apply_filter(gegl:gaussian-blur, std-dev 2.0)...")
        r = cmd('apply_filter', {
            'image_index': target_index,
            'operation':   'gegl:gaussian-blur',
            'properties':  {'std-dev-x': 2.0, 'std-dev-y': 2.0},
        })
        if r.get('status') != 'success':
            fail(f"apply_filter reported error: {r.get('error', '')}")
        results = r.get('results') or {}
        if results.get('operation') != 'gegl:gaussian-blur':
            fail(f"apply_filter echoed wrong op: {results!r}")
        applied = results.get('props_applied') or []
        if 'std-dev-x' not in applied or 'std-dev-y' not in applied:
            fail(f"props_applied missing std-dev-x/y: {applied!r}")
        print(f"PASS apply_filter: op={results.get('operation')} props={applied}")
    finally:
        try:
            cmd('close_image', {'image_index': target_index, 'save_first': False})
        except Exception as e:
            print(f"  (cleanup) close_image transport error: {e}", file=sys.stderr)


# ── entry point ───────────────────────────────────────────────────────────

def main():
    test_list_gegl_operations()
    test_get_pdb_procedure_info()
    test_apply_filter()
    print("ALL PASSED")
    sys.exit(0)


if __name__ == '__main__':
    main()
