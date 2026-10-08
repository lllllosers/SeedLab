"""The same updater, with legacy adoption and an embedded local package."""
import sys
sys.dont_write_bytecode = True
from production_ops.gui import main

if __name__ == "__main__":
    raise SystemExit(main(bootstrap=True))
