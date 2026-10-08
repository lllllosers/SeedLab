"""Stable launcher: intentionally does not import the GUI or database stack."""
import sys
sys.dont_write_bytecode = True
from production_ops.launcher import main

if __name__ == "__main__":
    raise SystemExit(main())
