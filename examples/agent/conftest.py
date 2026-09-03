"""Make the project importable when its tests are run in place."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = str(Path(__file__).parent)
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)
