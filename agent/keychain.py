"""
agent/keychain.py — the optional API key lives in the OS keychain (privacy rule P8).

Never in the database, the config file or the logs. macOS: Keychain; Windows: Credential Manager.
"""

from __future__ import annotations

import logging

import keyring
import keyring.errors

log = logging.getLogger(__name__)

SERVICE = "Commit"
USERNAME = "api_key"


def get_api_key() -> str | None:
    """The saved API key, or None (also when the keychain cannot be reached)."""
    try:
        return keyring.get_password(SERVICE, USERNAME)
    except keyring.errors.KeyringError:
        log.warning("Could not read the API key from the keychain.")
        return None


def set_api_key(api_key: str) -> None:
    """Save (or replace) the API key in the keychain."""
    keyring.set_password(SERVICE, USERNAME, api_key)


def delete_api_key() -> None:
    """Remove the API key (P9). Does nothing if there is none."""
    try:
        keyring.delete_password(SERVICE, USERNAME)
    except keyring.errors.PasswordDeleteError:
        pass  # no key was saved
    except keyring.errors.KeyringError:
        log.warning("Could not reach the keychain to delete the API key.")
