"""
tests/test_extension.py — the extension's page logic (extension/common.js), run with Node.

Checks what the extension would send for different pages: domain only (never the full URL),
"Private" for the private list, "Other" for Chrome's own pages. Skipped if Node is not installed.
"""

import json
import shutil
import subprocess
from pathlib import Path

import pytest

COMMON_JS = Path(__file__).resolve().parent.parent / "extension" / "common.js"
pytestmark = pytest.mark.skipif(shutil.which("node") is None, reason="Node.js is not installed")


def run_common(expression: str):
    """Evaluate a JavaScript expression with common.js loaded; return the JSON result."""
    script = f"const c = require({json.dumps(str(COMMON_JS))}); console.log(JSON.stringify({expression}));"
    output = subprocess.run(["node", "-e", script], capture_output=True, text=True, check=True).stdout
    return json.loads(output)


def describe(url: str, title: str = "A title", private: list | None = None, port: int = 8765):
    return run_common(f"c.describePage({json.dumps(url)}, {json.dumps(title)}, {json.dumps(private or [])}, {port})")


def test_commit_dashboard_is_reported_only_as_commit():
    for url in ["http://127.0.0.1:8765/", "http://127.0.0.1:8765/#/developer", "http://localhost:8765/#/settings"]:
        assert describe(url, "Commit") == {"category": "Commit"}
    assert describe("http://127.0.0.1:9000/", "Commit", port=9000) == {"category": "Commit"}
    # Other local pages (e.g. a dev server on another port) are ordinary sites.
    assert describe("http://localhost:3000/", "My app") == {"domain": "localhost", "title": "My app"}


def test_normal_site_sends_domain_and_title_not_url():
    result = describe("https://www.youtube.com/watch?v=abc123&t=42", "Contract Law Lecture 5")
    assert result == {"domain": "youtube.com", "title": "Contract Law Lecture 5"}


def test_private_site_sends_only_category():
    assert describe("https://online.bank.com/account", "Balance", ["bank.com"]) == {"category": "Private"}


def test_browser_pages_are_other():
    for url in ["chrome://newtab/", "chrome-extension://abc/popup.html", "file:///Users/me/a.pdf", "about:blank", "not a url"]:
        assert describe(url) == {"category": "Other"}


def test_private_matching_rules():
    assert run_common('c.isPrivate("bank.com", ["bank.com"])') is True
    assert run_common('c.isPrivate("notbank.com", ["bank.com"])') is False


def test_normalise_typed_domain():
    assert run_common('c.normaliseDomain("https://WWW.Bank.com/login")') == "bank.com"


def test_manifest_permissions_are_minimal():
    manifest = json.loads((COMMON_JS.parent / "manifest.json").read_text())
    assert manifest["manifest_version"] == 3
    assert manifest["host_permissions"] == ["http://127.0.0.1/*"]       # no other network access
    assert manifest["incognito"] == "not_allowed"
    assert set(manifest["permissions"]) == {"tabs", "idle", "alarms", "storage"}
