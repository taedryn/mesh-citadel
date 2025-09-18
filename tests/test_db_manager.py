import os
import pytest
import sqlite3
import tempfile

from citadel.db.manager import DatabaseManager
from citadel.loginit import initialize_logging


class DummyConfig:
    def __init__(self, path):
        self.database = {}
        self.database['db_path'] = path
        self.logging = {}
        self.logging['log_file_path'] = '/tmp/citadel.log'
        self.logging['log_level'] = 'DEBUG'

config = DummyConfig('foo')
initialize_logging(config)

@pytest.fixture(scope="function")
def db_manager():
    # reset the db manager
    DatabaseManager.reset()

    # Create a temporary SQLite file
    temp_db = tempfile.NamedTemporaryFile(delete=False)
    config = DummyConfig(temp_db.name)
    manager = DatabaseManager(config)

    if manager:
        print(f'created new database manager at {temp_db}')

    # Create a simple table for testing
    manager.execute("CREATE TABLE test (id INTEGER PRIMARY KEY, value TEXT)")

    yield manager

    print(f'shutting down database manager at {temp_db}')
    # Cleanup
    manager.shutdown()
    os.unlink(temp_db.name)

# -------------------------------
# ✅ Happy Path Tests
# -------------------------------

def test_insert_and_read(db_manager):
    db_manager.execute("INSERT INTO test (value) VALUES (?)", ("hello",))
    results = db_manager.execute("SELECT * FROM test")
    assert len(results) == 1
    assert results[0][1] == "hello"

def test_multiple_writes_queued(db_manager):
    for i in range(5):
        db_manager.execute("INSERT INTO test (value) VALUES (?)", (f"msg{i}",))
    results = db_manager.execute("SELECT * FROM test")
    assert len(results) == 5
    assert results[0][1] == "msg0"
    assert results[-1][1] == "msg4"

# -------------------------------
# ❌ Unhappy Path Tests
# -------------------------------

def test_invalid_sql_raises(db_manager):
    with pytest.raises(RuntimeError, match="Database read failed"):
        db_manager.execute("SELEC * FROM test")  # typo in SELECT

def test_invalid_params_raises(db_manager):
    with pytest.raises(RuntimeError, match="Database error occurred"):
        db_manager.execute("INSERT INTO test (value) VALUES (?)", ())  # missing param

def test_shutdown_closes_connection(db_manager):
    db_manager.shutdown()
    with pytest.raises(RuntimeError):
        db_manager.execute("SELECT * FROM test")

