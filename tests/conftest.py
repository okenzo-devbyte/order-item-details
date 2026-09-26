import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
for entry in (str(ROOT), str(SRC)):
    if entry not in sys.path:
        sys.path.insert(0, entry)

DATA_FILE = ROOT / "sample_order_data_1000_records.xlsx"
