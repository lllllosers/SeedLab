"""Console-capable server launcher, hidden by the control center on Windows."""
import sys

sys.dont_write_bytecode = True
from app.server_entry import main

if __name__ == "__main__":
    raise SystemExit(main())
