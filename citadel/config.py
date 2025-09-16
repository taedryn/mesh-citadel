import os
import yaml

class ConfigSection:
    def __init__(self, data, section_name):
        for key, value in data.items():
            setattr(self, key, value)
        self._section_name = section_name

class Config:
    _instance = None

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

    @classmethod
    def get(cls):
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    def __init__(self):
        self.config_path = os.getenv("CITADEL_CONFIG_PATH", "config.yaml")
        self.reload()

    def reload(self):
        config_data = self._load_yaml(self.config_path)
        # Merge defaults, YAML, environment
        merged = self._merge_dicts(self._defaults, config_data)
        merged = self._apply_env_vars(merged)
        # Set sections as attributes
        for section, values in merged.items():
            setattr(self, section, ConfigSection(values, section))
        # Check for missing/incomplete config
        self._validate_config(merged)

    def _load_yaml(self, path):
        try:
            with open(path, "r") as f:
                return yaml.safe_load(f) or {}
        except FileNotFoundError:
            print(f"[WARNING] Config file {path} not found. Using defaults.")
            return {}
        except yaml.YAMLError as e:
            print(f"[WARNING] YAML error in {path}: {e}. Using defaults.")
            return {}

    def _merge_dicts(self, base, update):
        result = {}
        for key, value in base.items():
            if key in update:
                if isinstance(value, dict) and isinstance(update[key], dict):
                    result[key] = self._merge_dicts(value, update[key])
                else:
                    result[key] = update[key]
            else:
                result[key] = value
        # Add any keys in update not in base
        for key, value in update.items():
            if key not in result:
                result[key] = value
        return result

    def _apply_env_vars(self, config):
        # For each nested config value, override with CITADEL_SECTION_KEY env var
        def apply_env(section, prefix=""):
            for key, value in section.items():
                env_var = f"CITADEL_{prefix}{key}".upper()
                if isinstance(value, dict):
                    section[key] = apply_env(value, prefix=f"{key}_")
                else:
                    if env_var in os.environ:
                        section[key] = os.environ[env_var]
            return section
        return apply_env(config)

    def _validate_config(self, config):
        # Print warnings for missing/poorly configured values
        def check(section, path=""):
            for key, value in section.items():
                full_key = f"{path}.{key}" if path else key
                if value is None or value == 