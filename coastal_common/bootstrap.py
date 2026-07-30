"""Ensure the repo root is on sys.path for region entrypoints."""
import sys
from pathlib import Path


def ensure_repo_root_on_path(region_file):
    """Insert repo root (parent of karnataka/ or pnw/) at the front of sys.path."""
    root = Path(region_file).resolve().parent.parent
    root_str = str(root)
    if root_str not in sys.path:
        sys.path.insert(0, root_str)
    return root
