#!/usr/bin/env python3
"""
Compatibility wrapper to run daily like script.

This file simply dispatches to `likeeveryday.py` so callers can use
`likeeveryone.py` as requested. It forwards command-line arguments.
"""
import os
import sys


def main() -> None:
    script = os.path.join(os.path.dirname(__file__), "likeeveryday.py")
    if not os.path.isfile(script):
        raise SystemExit("likeeveryday.py not found next to this wrapper")
    with open(script, "r", encoding="utf-8") as f:
        code = compile(f.read(), script, "exec")
    # Execute as if running the target directly (preserves sys.argv)
    globals_dict = {"__name__": "__main__", "__file__": script}
    exec(code, globals_dict)


if __name__ == "__main__":
    main()

