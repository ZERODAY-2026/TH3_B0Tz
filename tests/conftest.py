"""Make repo root importable for tests (legallens package + tests package)."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
