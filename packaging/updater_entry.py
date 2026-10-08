"""Independent offline updater with its own bundled runtime."""
import sys
sys.dont_write_bytecode = True
from production_ops.gui import main

if __name__ == "__main__":
    raise SystemExit(main())
