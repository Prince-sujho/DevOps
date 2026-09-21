import sys
from pathlib import Path

SUITE = Path(__file__).resolve().parents[1]
REPO = SUITE.parent
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(SUITE))
