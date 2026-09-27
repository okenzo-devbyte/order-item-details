from __future__ import annotations

import os
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PYTHON = ROOT / ".venv" / "Scripts" / "python.exe"


def test_the_script_reports_the_import_counts(tmp_path, client_db):
    """client_db guarantees the t_ schemas exist before the subprocess loads."""
    from conftest import TEST_URL

    env = dict(os.environ)
    env["PYTHONPATH"] = str(ROOT / "src")
    env["PYTHONIOENCODING"] = "utf-8"
    env["DATABASE_URL"] = TEST_URL
    env["DB_SCHEMA_ITEM"] = "t_item"
    env["DB_SCHEMA_SALES"] = "t_sales"
    env["DB_SCHEMA_APP"] = "t_app"
    result = subprocess.run(
        [
            str(PYTHON),
            str(ROOT / "scripts" / "load_postgres.py"),
            str(ROOT / "sample_order_data_1000_records.xlsx"),
            "--version",
            "2",
        ],
        capture_output=True,
        text=True,
        encoding="utf-8",
        cwd=ROOT,
        env=env,
    )
    assert result.returncode == 0, result.stderr
    assert "products       : 15" in result.stdout
    assert "customers      : 20" in result.stdout
    assert "orders         : 1000" in result.stdout
    assert "barcodes       : 127" in result.stdout


def test_the_script_writes_into_the_configured_schemas(client_db):
    assert (
        client_db.one('SELECT count(*) AS n FROM "t_item"."products_v2"')["n"] == 15
    )
    assert client_db.one('SELECT count(*) AS n FROM "t_sales"."orders"')["n"] == 1000
