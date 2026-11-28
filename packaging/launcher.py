"""PyInstaller entry point."""
import multiprocessing

from iuk_browser.__main__ import main

if __name__ == "__main__":
    multiprocessing.freeze_support()
    raise SystemExit(main())
