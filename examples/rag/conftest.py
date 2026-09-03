"""Make the project importable when its tests are run in place.

An ordinary Python project either is installed or says where it lives. This says where it
lives, which is what keeps `pytest` working straight out of a clone.
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = str(Path(__file__).parent)
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)
