"""Compat shim. Implementation: scripts/test_db.py."""
from pathlib import Path
import runpy

runpy.run_path(str(Path(__file__).resolve().parent / "scripts" / "test_db.py"), run_name="__main__")
