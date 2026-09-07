"""Shared pytest fixtures/path setup for the IMCR test-suite.

All tests run fully offline (dry-run judge mode, fixed seeds).
"""

import sys
from pathlib import Path

CODE_DIR = Path(__file__).resolve().parent.parent
EVAL_DIR = CODE_DIR / "independent_eval"
for p in (str(CODE_DIR), str(EVAL_DIR)):
    if p not in sys.path:
        sys.path.insert(0, p)
