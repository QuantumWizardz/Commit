"""
agent/config.py — read settings: defaults from config/default.yaml, user changes from the database.

Why this file exists: every threshold lives in the YAML file (README rule 5: no magic numbers).
When the user changes a setting in the app, the new value is saved in the database "settings"
table under the key "config_overrides" and wins over the YAML default.

Usage:
    config = Config(storage)
    config.get("breaks.load_threshold")      -> 70
    config.set("dnd.mode", "auto")           # saved in the database
"""

from __future__ import annotations

import copy
from pathlib import Path
from typing import Any

import yaml

# Project folder = the folder above agent/.
PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_CONFIG_FILE = PROJECT_ROOT / "config" / "default.yaml"

# Name of the settings row that holds the user's overrides.
OVERRIDES_KEY = "config_overrides"


def load_default_config(path: Path = DEFAULT_CONFIG_FILE) -> dict:
    """
    Read the default configuration file.

    In:  path to a YAML file.
    Out: the configuration as a nested dict.
    """
    with open(path, encoding="utf-8") as file:
        return yaml.safe_load(file)


def read_dotted(tree: dict, dotted_key: str) -> Any:
    """
    Read a value from a nested dict with a "section.name" key.

    In:  nested dict, key like "breaks.load_threshold".
    Out: the value. Raises KeyError if it does not exist.
    """
    value: Any = tree
    for part in dotted_key.split("."):
        value = value[part]
    return value


class Config:
    """Configuration = YAML defaults + user overrides stored in the database."""

    def __init__(self, storage=None, defaults: dict | None = None):
        """
        In:  storage — an agent.storage.Storage (or None for defaults only, e.g. in tests);
             defaults — optional dict instead of the YAML file.
        """
        self.storage = storage
        self.defaults = defaults if defaults is not None else load_default_config()

    def overrides(self) -> dict:
        """The user's saved changes as {"section.name": value}."""
        if self.storage is None:
            return {}
        return self.storage.get_setting(OVERRIDES_KEY, {})

    def get(self, dotted_key: str) -> Any:
        """
        Read one setting, preferring the user's override.

        In:  key like "dnd.mode".
        Out: the value (a copy, so callers cannot change the defaults by accident).
        """
        saved = self.overrides()
        if dotted_key in saved:
            return saved[dotted_key]
        return copy.deepcopy(read_dotted(self.defaults, dotted_key))

    def set(self, dotted_key: str, value: Any) -> None:
        """
        Save a user change.

        In:  key like "dnd.mode" (must exist in the defaults) and the new value.
        """
        read_dotted(self.defaults, dotted_key)  # raises KeyError for unknown keys
        saved = self.overrides()
        saved[dotted_key] = value
        self.storage.set_setting(OVERRIDES_KEY, saved)
