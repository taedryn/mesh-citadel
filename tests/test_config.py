import os
import tempfile
import shutil
import pytest
from yaml.parser import ParserError

from citadel.config import Config


@pytest.fixture
def temp_config_dir():
    path = tempfile.mkdtemp()
    yield path
    shutil.rmtree(path)


def write_config(path, content):
    with open(path, "w", encoding="utf-8") as f:
        f.write(content)


def reset_config_singleton():
    Config._instance = None
    Config._initialized = False


def test_basic_load(temp_config_dir):
    reset_config_singleton()
    config_path = os.path.join(temp_config_dir, "config.yaml")
    write_config(config_path, "bbs:\n  system_name: 'Test Citadel'")
    cfg = Config(config_path)
    assert cfg.bbs["system_name"] == "Test Citadel"
    assert cfg.bbs["max_messages_per_room"] == 300  # from defaults


def test_env_override(monkeypatch, temp_config_dir):
    reset_config_singleton()
    monkeypatch.setenv("CITADEL_BBS__SYSTEM_NAME", "Env Citadel")
    config_path = os.path.join(temp_config_dir, "config.yaml")
    write_config(config_path, "bbs:\n  system_name: 'File Citadel'")
    cfg = Config(config_path)
    assert cfg.bbs["system_name"] == "Env Citadel"


def test_missing_file_uses_defaults():
    reset_config_singleton()
    cfg = Config("nonexistent.yaml")
    assert cfg.bbs["system_name"] == "Mesh-Citadel"
    assert cfg.transport["serial_port"] == "/dev/ttyUSB0"


def test_bad_yaml_format(temp_config_dir):
    reset_config_singleton()
    config_path = os.path.join(temp_config_dir, "config.yaml")
    write_config(config_path, "bbs: [unclosed")
    with pytest.raises(ParserError):
        Config(config_path)


def test_invalid_value_type(temp_config_dir):
    reset_config_singleton()
    config_path = os.path.join(temp_config_dir, "config.yaml")
    write_config(config_path, "bbs:\n  max_messages_per_room: 'not a number'")
    with pytest.raises(AssertionError):
        Config(config_path)


def test_reload_preserves_reboot_only_keys(temp_config_dir):
    reset_config_singleton()
    config_path = os.path.join(temp_config_dir, "config.yaml")
    write_config(
        config_path, "bbs:\n  system_name: 'Initial'\n  max_messages_per_room: 300")
    cfg = Config(config_path)
    write_config(
        config_path, "bbs:\n  system_name: 'Updated'\n  max_messages_per_room: 999")
    with pytest.raises(RuntimeError):
        cfg.reload()


def test_reload_allows_safe_changes(temp_config_dir):
    reset_config_singleton()
    config_path = os.path.join(temp_config_dir, "config.yaml")
    write_config(config_path, "bbs:\n  system_name: 'Initial'")
    cfg = Config(config_path)
    write_config(config_path, "bbs:\n  system_name: 'Updated'")
    cfg.reload()
    assert cfg.bbs["system_name"] == "Updated"
