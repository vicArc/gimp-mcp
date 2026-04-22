#!/usr/bin/env python3
"""Live test: posterize applies gimp-drawable-posterize."""
from tests._harness import cmd, fail, passed, canvas

with canvas(width=80, height=60, fill="#8877aa") as idx:
    r = cmd('posterize', {'image_index': idx, 'levels': 4})
    if r.get('status') != 'success':
        fail(f"posterize error: {r.get('error', '')}")
    if (r.get('results') or {}).get('levels') != 4:
        fail(f"unexpected levels echo: {r!r}")

passed("posterize: 4 levels applied")
