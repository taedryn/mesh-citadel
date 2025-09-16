import os
import yaml
import pytest
from unittest import mock
from citadel import config

@pytest.fixture(autouse=True)
def cleanup_env_vars():
    # Remove CITADEL_ env vars before/after test to prevent pollution
    old_env = {k: v for k, v in os.environ.items() if k.startswith("CITADEL_")}
    for k in old_env: del os.environ[k]
    yield
    for k, v in old_env.items(): os.environ[k] = v

def test_config_defaults(monkeypatch):
    # Patch config path to a non-existent file so defaults load
    monkeypatch.setenv("CITADEL_CONFIG_PATH", "nonexistent.yaml")
    cfg = config.Config.get()
    assert cfg.bbs.system_name == "Mesh-Citadel"
    assert cfg.database.db_path == "citadel.db"
    assert isinstance(cfg.auth.recovery_questions, list)
    assert cfg.logging.log_level == "INFO"
    assert cfg.transport.serial_port == "/dev/ttyUSB0"

def test_config_yaml_loading(tmp_path, monkeypatch):
    test_yaml = {
        "bbs": {"system_name": "TestBBS", "max_rooms": 99},
        "database": {"db_path": "test.db"},
        "logging": {"log_level": "DEBUG"},
    }
    yaml_path = tmp_path / "config.yaml"
    yaml_path.write_text(yaml.dump(test_yaml))
    monkeypatch.setenv("CITADEL_CONFIG_PATH", str(yaml_path))
    cfg = config.Config()
    assert cfg.bbs.system_name == "TestBBS"
    assert cfg.bbs.max_rooms == 99
    assert cfg.database.db_path == "test.db"
    assert cfg.logging.log_level == "DEBUG"
    # Defaults fill missing
    assert cfg.bbs.max_users == 300

def test_env_override(monkeypatch):
    monkeypatch.setenv("CITADEL_BBS_SYSTEM_NAME", "EnvCitadel")
    monkeypatch.setenv("CITADEL_DATABASE_DB_PATH", "env.db")
    cfg = config.Config()
    assert cfg.bbs.system_name == "EnvCitadel"
    assert cfg.database.db_path == "env.db"

def test_reload(monkeypatch):
    # Changing YAML file updates config on reload
    yaml_1 = {"bbs": {"system_name": "Reload1"}}
    yaml_2 = {"bbs": {"system_name": "Reload2"}}
    yaml_path = "test_reload.yaml"
    with open(yaml_path, "w") as f:
        yaml.dump(yaml_1, f)
    monkeypatch.setenv("CITADEL_CONFIG_PATH", yaml_path)
    cfg = config.Config()
    assert cfg.bbs.system_name == "Reload1"
    with open(yaml_path, "w") as f:
        yaml.dump(yaml_2, f)
    cfg.reload()
    assert cfg.bbs.system_name == "Reload2"
    os.remove(yaml_path)
