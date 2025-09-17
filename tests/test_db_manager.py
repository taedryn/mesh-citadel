import os
import tempfile
import pytest
import sqlite3
from mesh_citadel.database_manager import DatabaseManager

class DummyConfig:
    def __init__(self, path):
        self.DATABASE_PATH = path

@pytest.fixture(scope="function")
def db_manager():
    # Create a temporary SQLite file
    temp_db = tempfile.NamedTemporaryFile(delete=False)
    config = DummyConfig(temp_db.name)
    manager = DatabaseManager(config)

    # Create a simple table for testing
    manager.execute("CREATE TABLE test (id INTEGER PRIMARY KEY,
value TEXT)")

    yield manager

    # Cleanup
    manager.shutdown()
    os.unlink(temp_db.name)

# -------------------------------
# ✅ Happy Path Tests
# -------------------------------

def test_insert_and_read(db_manager):
    db_manager.execute("INSERT INTO test (value) VALUES (?)",
("hello",))
    results = db_manager.execute("SELECT * FROM test")
    assert len(results) == 1
    assert results[0][1] == "hello"

def test_multiple_writes_queued(db_manager):
    for i in range(5):
        db_manager.execute("INSERT INTO test (value) VALUES (?)",
(f"msg{i}",))
    results = db_manager.execute("SELECT * FROM test")
    assert len(results) == 5
    assert results[0][1] == "msg0"
    assert results[-1][1] == "msg4"

def test_read_waits_for_writes(db_manager):
    db_manager.execute("INSERT INTO test (value) VALUES (?)",
("queued",))
    results = db_manager.execute("SELECT * FROM test")
    assert any(row[1] == "queued" for row in results)

# -------------------------------
# ❌ Unhappy Path Tests
# -------------------------------

def test_invalid_sql_raises(db_manager):
    with pytest.raises(RuntimeError, match="Database read failed"):
        db_manager.execute("SELEC * FROM test")  # typo in SELECT

def test_invalid_params_raises(db_manager):
    with pytest.raises(RuntimeError, match="Database write failed"):
        db_manager.execute("INSERT INTO test (value) VALUES (?)",
())  # missing param

def test_shutdown_closes_connection(db_manager):
    db_manager.shutdown()
    with pytest.raises(sqlite3.ProgrammingError):
        db_manager.execute("SELECT * FROM test")

