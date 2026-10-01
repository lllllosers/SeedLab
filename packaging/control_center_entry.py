"""Windowed portable launcher; all application logic remains in control_center."""
import sys

# External migration resources are read-only in the portable layout.
sys.dont_write_bytecode = True
from control_center.app import main

if __name__ == "__main__":
    raise SystemExit(main())
