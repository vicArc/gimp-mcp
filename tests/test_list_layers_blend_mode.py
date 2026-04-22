#!/usr/bin/env python3
"""Live test: list_layers returns human-readable blend_mode strings (Bug #5 regression)."""
from tests._harness import cmd, fail, passed, canvas

with canvas(width=80, height=60) as idx:
    # Create an extra layer in a non-normal blend mode
    cmd('create_layer', {'image_index': idx, 'name': 'multiply_layer', 'blend_mode': 'MULTIPLY'})

    r = cmd('list_layers', {'image_index': idx})
    if r.get('status') != 'success':
        fail(f"list_layers error: {r.get('error', '')}")

    layers = (r.get('results') or {}).get('layers', [])
    if not layers:
        fail("list_layers returned empty layer list")

    for layer in layers:
        bm = layer.get('blend_mode', '')
        # blend_mode must be a name string, never a raw integer
        try:
            int(bm)
            fail(f"layer '{layer.get('name')}' has numeric blend_mode={bm!r} — should be a name string")
        except ValueError:
            pass  # good — it's not a bare integer

    # Specifically verify the multiply layer roundtrips
    multiply = next((l for l in layers if l.get('name') == 'multiply_layer'), None)
    if multiply is None:
        fail("multiply_layer not found in list_layers output")
    if multiply.get('blend_mode') not in ('MULTIPLY',):
        fail(f"expected blend_mode='MULTIPLY', got {multiply.get('blend_mode')!r}")

passed(f"list_layers: all {len(layers)} layer(s) return named blend_mode strings")
