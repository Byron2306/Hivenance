"""Repository-local pytest bootstrap.

Termux/Python 3.14 may invoke pytest with tests/ at sys.path[0] instead of the
repository root. Keep production imports unchanged and make the repo root
explicit for the test session.
"""
from __future__ import annotations
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
root = str(ROOT)
if root not in sys.path:
    sys.path.insert(0, root)
