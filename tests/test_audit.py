from api.app_db import AppDB
from api.audit import list_entries, record


def test_record_and_list(tmp_path):
    db = AppDB(tmp_path / "app.db")
    record(db, action="search", user_id=None, query="สุรชัย", mode="customer", result_count=1)
    record(db, action="login_failed", query="admin")
    entries = list_entries(db)
    assert len(entries) == 2
    assert entries[0]["action"] == "login_failed"
    assert entries[1]["query"] == "สุรชัย"
    db.close()


def test_filters(tmp_path):
    db = AppDB(tmp_path / "app.db")
    record(db, action="search", user_id=1, query="a")
    record(db, action="import", user_id=1)
    assert len(list_entries(db, action="search")) == 1
    assert len(list_entries(db, user_id=1)) == 2
    assert len(list_entries(db, action="nope")) == 0
    db.close()


def test_before_id_pagination(tmp_path):
    db = AppDB(tmp_path / "app.db")
    for i in range(5):
        record(db, action="search", query=str(i))
    page = list_entries(db, limit=2)
    assert len(page) == 2
    older = list_entries(db, limit=10, before_id=page[-1]["id"])
    assert all(entry["id"] < page[-1]["id"] for entry in older)
    db.close()
