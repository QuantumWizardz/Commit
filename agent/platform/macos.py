"""
agent/platform/macos.py — everything that is specific to macOS.

Why this file exists: the rest of the agent calls these few functions and never talks to
macOS directly, so Phase 4 can add windows.py with the same functions (README section 11).

Functions:
    get_frontmost_app()            name of the app in front
    notify(title, message)         banner notification
    ask(prompt, buttons, ...)      dialog with up to 3 buttons, closes itself after a timeout
    ask_text(prompt, ...)          dialog with a text field (optionally hidden, for secrets)
    choose(prompt, items, ...)     pick one item from a list, closes itself after a timeout
    run_shortcut(name)             run a macOS Shortcut (used for Do Not Disturb)
    shortcut_exists(name)          is that Shortcut installed?
    open_url(url)                  open a web page or a System Settings pane
    open_privacy_settings(pane)    open Privacy & Security at a given pane

Errors never crash the agent: functions log the problem and return a "nothing happened" value.
"""

from __future__ import annotations

import logging
import subprocess

log = logging.getLogger(__name__)

DIALOG_TITLE = "Commit"

# Extra seconds we wait for osascript itself after a dialog's own timeout.
PROCESS_GRACE_SECONDS = 10

# How long running or listing a Shortcut may take.
SHORTCUT_TIMEOUT_SECONDS = 30

# System Settings → Privacy & Security panes we send the user to during setup.
PRIVACY_PANES = {
    "accessibility": "Privacy_Accessibility",
    "input_monitoring": "Privacy_ListenEvent",
    "automation": "Privacy_Automation",
}


# ---------------------------------------------------------------- helpers

def applescript_text(text: str) -> str:
    """
    Turn Python text into a quoted AppleScript string.

    In:  any text.
    Out: the text in double quotes with backslashes and quotes escaped.
    Why: a quote inside a message would otherwise break the script.
    """
    escaped = text.replace("\\", "\\\\").replace('"', '\\"')
    return f'"{escaped}"'


def applescript_list(items: list[str]) -> str:
    """Turn a list of texts into an AppleScript list, e.g. {"Yes", "No"}."""
    return "{" + ", ".join(applescript_text(item) for item in items) + "}"


def run_osascript(script: str, timeout_seconds: float) -> str | None:
    """
    Run an AppleScript and return what it printed.

    In:  the script text and the longest time to wait.
    Out: the printed result (stripped), or None if it failed or took too long.
         When it takes too long, the osascript process is killed, which also closes its dialog.
    """
    try:
        result = subprocess.run(
            ["osascript", "-e", script], capture_output=True, text=True, timeout=timeout_seconds
        )
    except subprocess.TimeoutExpired:
        log.info("Dialog timed out and was closed.")
        return None
    except OSError as error:
        log.warning("Could not run osascript: %s", error)
        return None
    if result.returncode != 0:
        # Error -128 = the user pressed Cancel / closed the dialog. Not worth a warning.
        if "-128" not in result.stderr:
            log.warning("osascript failed (code %s).", result.returncode)
        return None
    return result.stdout.strip()


# ---------------------------------------------------------------- the platform functions

def get_frontmost_app() -> str | None:
    """
    Name of the application in front, e.g. "Safari" (no window titles).

    Out: the app name, or None if it cannot be read.
    Note: needs a running macOS main loop (the menu-bar app provides it) to stay up to date.
    """
    try:
        from AppKit import NSWorkspace  # imported here so the rest of the agent loads without pyobjc

        application = NSWorkspace.sharedWorkspace().frontmostApplication()
        return str(application.localizedName()) if application is not None else None
    except Exception as error:  # pyobjc errors have many types; never crash the tracker
        log.warning("Could not read the frontmost app: %s", error)
        return None


def notify(title: str, message: str) -> None:
    """Show a banner notification. Never blocks for long, never raises."""
    script = f"display notification {applescript_text(message)} with title {applescript_text(title)}"
    run_osascript(script, timeout_seconds=PROCESS_GRACE_SECONDS)


def ask(prompt: str, buttons: list[str], default_button: str | None = None, timeout_seconds: int = 30) -> str | None:
    """
    Show a dialog with up to 3 buttons.

    In:  the question, button labels (max 3, macOS limit), the default button, timeout.
    Out: the label of the clicked button, or None if the dialog timed out or failed.
    """
    default_button = default_button or buttons[-1]
    script = (
        f"display dialog {applescript_text(prompt)} with title {applescript_text(DIALOG_TITLE)} "
        f"buttons {applescript_list(buttons)} default button {applescript_text(default_button)} "
        f"giving up after {int(timeout_seconds)}"
    )
    output = run_osascript(script, timeout_seconds + PROCESS_GRACE_SECONDS)
    # Output looks like: "button returned:Yes, gave up:false"
    if output is None or "gave up:true" in output:
        return None
    for button in buttons:
        if f"button returned:{button}" in output:
            return button
    return None


def ask_text(prompt: str, default_text: str = "", hidden: bool = False, timeout_seconds: int = 30) -> str | None:
    """
    Dialog with a text field (used to show the pairing token and to type an API key).

    In:  the message, the text already in the field, hidden=True for secrets (shows dots), timeout.
    Out: the text when OK was pressed, or None (Cancel / timeout). The text is never logged.
    """
    hidden_part = " with hidden answer" if hidden else ""
    script = (
        f"set reply to display dialog {applescript_text(prompt)} default answer {applescript_text(default_text)}{hidden_part} "
        f"with title {applescript_text(DIALOG_TITLE)} buttons {{\"Cancel\", \"OK\"}} default button \"OK\" "
        f"cancel button \"Cancel\" giving up after {int(timeout_seconds)}\n"
        "if gave up of reply then return \"\"\n"
        "return \"OK:\" & text returned of reply"
    )
    output = run_osascript(script, timeout_seconds + PROCESS_GRACE_SECONDS)
    if output is None or not output.startswith("OK:"):
        return None
    return output[len("OK:"):]


def choose(prompt: str, items: list[str], timeout_seconds: int = 30) -> str | None:
    """
    Let the user pick one item from a list (used when more than 3 answers are possible).

    In:  the question, the items, timeout.
    Out: the chosen item, or None if cancelled / timed out.
    """
    script = (
        f"choose from list {applescript_list(items)} with prompt {applescript_text(prompt)} "
        f"with title {applescript_text(DIALOG_TITLE)} default items {applescript_list(items[:1])}"
    )
    # "choose from list" has no built-in timeout, so the process is killed after the timeout.
    output = run_osascript(script, timeout_seconds)
    if output is None or output == "false":
        return None
    return output if output in items else None


def run_shortcut(name: str) -> bool:
    """
    Run a macOS Shortcut by name.

    In:  the Shortcut name, e.g. "Commit Focus On".
    Out: True if it ran successfully.
    """
    try:
        result = subprocess.run(["shortcuts", "run", name], capture_output=True, text=True, timeout=SHORTCUT_TIMEOUT_SECONDS)
    except (OSError, subprocess.TimeoutExpired) as error:
        log.warning("Running shortcut %r failed: %s", name, error)
        return False
    if result.returncode != 0:
        log.warning("Shortcut %r returned code %s.", name, result.returncode)
    return result.returncode == 0


def shortcut_exists(name: str) -> bool:
    """True if a Shortcut with exactly this name is installed."""
    try:
        result = subprocess.run(["shortcuts", "list"], capture_output=True, text=True, timeout=SHORTCUT_TIMEOUT_SECONDS)
    except (OSError, subprocess.TimeoutExpired) as error:
        log.warning("Listing shortcuts failed: %s", error)
        return False
    return name in result.stdout.splitlines()


def open_url(url: str) -> None:
    """Open a URL (web page or x-apple.systempreferences link) with the default handler."""
    try:
        subprocess.run(["open", url], capture_output=True, timeout=PROCESS_GRACE_SECONDS)
    except (OSError, subprocess.TimeoutExpired) as error:
        log.warning("Could not open %s: %s", url, error)


def open_privacy_settings(pane: str) -> None:
    """
    Open System Settings → Privacy & Security at a pane.

    In:  "accessibility", "input_monitoring" or "automation".
    """
    open_url(f"x-apple.systempreferences:com.apple.preference.security?{PRIVACY_PANES[pane]}")
