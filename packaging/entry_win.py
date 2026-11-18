"""PyInstaller entry point for Manage Eco (eco.exe)."""
import sys
from manage_eco.cli import main

if __name__ == "__main__":
    sys.exit(main())
