"""Shared pytest configuration.

Adds the backend root to sys.path so tests can import `app.*` without
needing an editable install.
"""

import sys
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))
