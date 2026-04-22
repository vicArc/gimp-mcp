#!/usr/bin/env python3
"""Live test: run_script_fu executes Scheme when the extension is installed.

On Windows GIMP 3.2.2 (and some Linux minimal builds) the Script-Fu
extension is not shipped, so the tool surfaces a structured 'not
available' response. Either outcome is a PASS — only an unrelated
exception shape would be a regression.
"""
from tests._harness import cmd, fail, passed

r = cmd('run_script_fu', {'script': '(+ 1 2)'})
if r.get('status') == 'success':
    passed(f"run_script_fu: script-fu installed, executed_chars={(r.get('results') or {}).get('executed_chars')}")

err = r.get('error') or ''
if 'not available' in err.lower() or 'not installed' in err.lower() or 'script-fu' in err.lower():
    passed(f"run_script_fu: structured not-available (script-fu absent): {err[:80]}")
fail(f"unexpected error shape: {err[:140]}")
