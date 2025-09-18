import os
import yaml
import copy
import logging

log = logging.getLogger(__name__)
log.setLevel(logging.INFO)

ENV_PREFIX = "CITADEL_"


class Config:
    _instance = None
    _initialized = False

    _defaults = {
        "bbs": {
            "system_name": "Mesh-Citadel",
            "max_messages_per_room": 300,
            "max_rooms": 50,
            "max_users": 300,
            "mail_message_limit": 50,
            "starting_room": "Lobby",
            "export_format": "json"
        },
        "auth": {
            "session_timeout": 3600,
            "max_password_length": 64,
            "max_username_length": 32,
            "recovery_questions": [
                "What is your favorite color?",
                "What was your first pet's name?",
                "Who was your favorite teacher?"
            ]
        },
        "transport": {
            "serial_port": "/dev/ttyUSB0",
            "baud_rate": 9600,
        },
        "database": {
            "db_path": "citadel.db",
        },
        "logging": {
            "log_level": "INFO",
            "log_file_path": "citadel.log",
        }
    }

    _reboot_only_keys = {
        "bbs.max_messages_per_room",
        "bbs.max_rooms",
        "bbs.max_users",
    }

    def __new__(cls, path="config.yaml"):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self, path="config.yaml"):
        if self.__class__._initialized:
            return
        self._path = path
        self._load()
        self.__class__._initialized = True

    def _load(self):
        try:
            with open(self._path, "r", encoding="utf-8") as f:
                raw = yaml.safe_load(f) or {}
        except FileNotFoundError:
            msg = "Failed to open config file {self._path}, reverting to defaults"
            log.warning(msg)
            print(msg)
            raw = {}

        raw = self._deep_merge(copy.deepcopy(self._defaults), raw)
        raw = self._apply_env_overrides(raw)
        self._validate(raw)

        self._raw = raw

        self.bbs = raw["bbs"]
        self.auth = raw["auth"]
        self.transport = raw["transport"]
        self.database = raw["database"]
        self.logging = raw["logging"]

        self._reboot_snapshot = {
            key: self._get_nested(raw, key.split("."))
            for key in self._reboot_only_keys
        }

    def reload(self):
        with open(self._path, "r", encoding="utf-8") as f:
            new_raw = yaml.safe_load(f) or {}

        new_raw = self._deep_merge(copy.deepcopy(self._defaults), new_raw)
        new_raw = self._apply_env_overrides(new_raw)
        self._validate(new_raw)

        for key, old_val in self._reboot_snapshot.items():
            new_val = self._get_nested(new_raw, key.split("."))
            if new_val != old_val:
                raise RuntimeError(
                    f"Cannot change reboot-only config key '{key}' at runtime")

        self._raw = new_raw

        self.bbs = new_raw["bbs"]
        self.auth = new_raw["auth"]
        self.transport = new_raw["transport"]
        self.database = new_raw["database"]
        self.logging = new_raw["logging"]

    def _apply_env_overrides(self, raw):
        overrides = {}
        for key, val in os.environ.items():
            if not key.startswith(ENV_PREFIX):
                continue
            path = key[len(ENV_PREFIX):].lower().split("__")
            self._set_nested(overrides, path, self._coerce(val))
        return self._deep_merge(raw, overrides)

    def _set_nested(self, d, path, value):
        for key in path[:-1]:
            d = d.setdefault(key, {})
        d[path[-1]] = value

    def _get_nested(self, d, path):
        for key in path:
            d = d.get(key, {})
        return d if not isinstance(d, dict) else copy.deepcopy(d)

    def _coerce(self, val):
        if val.lower() in ("true", "false"):
            return val.lower() == "true"
        if val.isdigit():
            return int(val)
        try:
            return float(val)
        except ValueError:
            return val

    def _deep_merge(self, base, extra):
        merged = dict(base)
        for k, v in extra.items():
            if isinstance(v, dict) and isinstance(merged.get(k), dict):
                merged[k] = self._deep_merge(merged[k], v)
            else:
                merged[k] = v
        return merged

    def _validate(self, cfg):
        assert cfg["bbs"]["system_name"], "bbs.system_name is required"
        assert isinstance(cfg["bbs"]["max_messages_per_room"],
                          int), "bbs.max_messages_per_room must be int"
        assert isinstance(cfg["auth"]["session_timeout"],
                          int), "auth.session_timeout must be int"
        assert cfg["transport"]["baud_rate"], "transport.baud_rate is required"
        assert cfg["transport"]["serial_port"], "transport.serial_port is required"
        assert cfg["database"]["db_path"], "database.db_path is required"
