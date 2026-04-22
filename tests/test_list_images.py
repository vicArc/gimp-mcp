#!/usr/bin/env python3
"""Live test: list_images returns a list (empty or with open images)."""
from tests._harness import cmd, fail, passed

r = cmd('list_images', {})
if r.get('status') != 'success':
    fail(f"list_images returned error: {r.get('error', '')}")

results = r.get('results') or {}
images = results.get('images')
if not isinstance(images, list):
    fail(f"images field is not a list: {images!r}")

passed(f"list_images: {len(images)} images open")
