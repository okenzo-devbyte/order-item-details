import os
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
for entry in (str(ROOT), str(SRC)):
    if entry not in sys.path:
        sys.path.insert(0, entry)

DATA_FILE = ROOT / "sample_order_data_1000_records.xlsx"

TEST_SCHEMAS = ("t_item", "t_sales", "t_app")


def _test_dsn() -> str:
    explicit = os.environ.get("TEST_DATABASE_URL", "")
    if explicit:
        return explicit
    env_file = ROOT / ".env"
    if env_file.is_file():
        for line in env_file.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line.startswith("DATABASE_URL="):
                return line.split("=", 1)[1].strip().strip('"').strip("'")
    return ""


TEST_URL = _test_dsn()


def pytest_collection_modifyitems(config, items):
    if TEST_URL:
        return
    skip = pytest.mark.skip(reason="no DATABASE_URL in the environment or .env")
    for item in items:
        if "client_db" in getattr(item, "fixturenames", ()):
            item.add_marker(skip)


@pytest.fixture(scope="session")
def client_db():
    from api.db import Database

    database = Database(TEST_URL, *TEST_SCHEMAS)
    for schema in TEST_SCHEMAS:
        database.execute_script(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE;')
    database.migrate()
    yield database
    for schema in TEST_SCHEMAS:
        database.execute_script(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE;')
    database.close()
