"""
agent/consent.py — first-launch consent and setup (README section 4.1 and module M1.1).

Uses simple native dialogs (allowed by README 8.1). Steps:
  1. Welcome + link to the privacy policy.
  2. Five SEPARATE consent switches. Activity counts are required to use the app.
  3. macOS permissions (Accessibility, Input Monitoring; Automation is asked by macOS later).
  4. Creating the two Shortcuts for Do Not Disturb, with Test buttons.
  5. "Urgent = your allowlist" explanation.
  6. Calibration starts (Learning your normal pattern…).

The consent choices, the consent version and the date are saved in the settings table.
They can be changed later from the menu (Settings → Consent choices…).
"""

from __future__ import annotations

from datetime import date
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
PRIVACY_POLICY = PROJECT_ROOT / "docs" / "PRIVACY.md"
SHORTCUTS_GUIDE = PROJECT_ROOT / "docs" / "SHORTCUTS_SETUP.md"

CONSENT_KEY = "consent"
ONBOARDING_KEY = "onboarding_complete"
CONSENT_VERSION = 1

# (key, title, plain-language explanation, required?, default answer)
CONSENT_ITEMS = [
    ("activity_counts", "1. Activity counts (required)",
     "Commit counts how many keys you press and how much you use the mouse each minute, and notes which app "
     "is in front. It never records WHAT you type, passwords, the clipboard, screenshots, the camera or the "
     "microphone. Commit cannot work without this.", True, True),
    ("website_tracking", "2. Website tracking (Chrome extension)",
     "The Chrome extension reports the website domain and time spent. Page titles are used only to choose a "
     "category and are then thrown away. Sites on your 'Don't track' list show only as 'Private'.", False, True),
    ("title_local", "3. Title categorisation on this computer",
     "A local AI model (Ollama) running on this computer sorts page/video titles into categories. "
     "Nothing leaves your computer.", False, True),
    ("title_api", "4. Title categorisation with my own API key",
     "Off unless you turn it on. WARNING: shortened titles, with e-mails, links and long numbers removed, "
     "would be sent to the AI provider whose API key you enter.", False, False),
    ("checkins", "5. Load check-in pop-ups",
     "About every 45 minutes of active work, Commit asks 'How mentally loaded do you feel right now?' (1–5). "
     "Your answers personalise the load score.", False, True),
]

WELCOME_TEXT = (
    "Welcome to Commit.\n\n"
    "Commit runs quietly in the background, notices when you are working under interruptions or time "
    "pressure, and offers Do Not Disturb or a short break. Everything stays on this computer: no account, "
    "no cloud.\n\nNext you choose what Commit may do. You can change this later."
)
PERMISSIONS_TEXT = (
    "macOS permissions\n\n"
    "• Accessibility and Input Monitoring: needed to COUNT keyboard and mouse activity. Add the app that "
    "runs Commit (Terminal or Visual Studio Code) in both lists, then restart Commit.\n"
    "• Automation: macOS will ask later, the first time Commit runs a Shortcut for Do Not Disturb."
)
SHORTCUTS_TEXT = (
    "Do Not Disturb setup (one time)\n\n"
    "Open the Shortcuts app and create two shortcuts:\n"
    "• \"{on}\" with the action Set Focus → Do Not Disturb → On\n"
    "• \"{off}\" with the action Set Focus → Do Not Disturb → Off\n\n"
    "Then use the Test buttons. Step-by-step guide: docs/SHORTCUTS_SETUP.md"
)
ALLOWLIST_TEXT = (
    "Urgent notifications\n\n"
    "When Do Not Disturb is on, only people and apps on YOUR allowlist can still notify you. Choose them in "
    "System Settings → Focus → Do Not Disturb → Allowed People / Allowed Apps. Commit never reads your messages."
)
CALIBRATION_TEXT = "Learning your normal pattern… Work as usual. Commit starts helping after 15 active minutes."


def ask_consent_choices(system, timeout_seconds: int) -> dict | None:
    """
    Ask the five consent questions, one dialog each.

    In:  platform module, dialog timeout.
    Out: {key: True/False} for all five items;
         {"activity_counts": False} if the user refused the required item (stop the app);
         None if a dialog timed out (keep whatever was saved before).
    """
    choices = {}
    for key, title, explanation, required, default_yes in CONSENT_ITEMS:
        if required:
            buttons, yes_label = ["Quit Commit", "I agree"], "I agree"
        else:
            buttons, yes_label = ["No", "Yes"], "Yes"
        default = yes_label if default_yes else buttons[0]
        answer = system.ask(f"{title}\n\n{explanation}", buttons, default_button=default, timeout_seconds=timeout_seconds)
        if answer is None:
            return None
        choices[key] = answer == yes_label
        if required and not choices[key]:
            return {key: False}
    return choices


def save_consent(storage, choices: dict) -> None:
    """Save the consent choices with the consent version and today's date."""
    storage.set_setting(CONSENT_KEY, {"version": CONSENT_VERSION, "date": date.today().isoformat(), "choices": choices})


def welcome_step(system, timeout_seconds: int) -> bool:
    """Show the welcome text. Out: True to continue, False if the user quits."""
    while True:
        answer = system.ask(WELCOME_TEXT, ["Quit", "Read privacy policy", "Continue"], default_button="Continue", timeout_seconds=timeout_seconds)
        if answer == "Read privacy policy":
            system.open_url(PRIVACY_POLICY.as_uri())
            continue
        return answer == "Continue"


def permissions_step(system, timeout_seconds: int) -> None:
    """Guide the user to the two Privacy & Security panes."""
    while True:
        answer = system.ask(PERMISSIONS_TEXT, ["Open Accessibility", "Open Input Monitoring", "Continue"], default_button="Continue", timeout_seconds=timeout_seconds)
        if answer == "Open Accessibility":
            system.open_privacy_settings("accessibility")
        elif answer == "Open Input Monitoring":
            system.open_privacy_settings("input_monitoring")
        else:
            return


def test_shortcut(system, name: str, timeout_seconds: int) -> None:
    """Run one Shortcut and tell the user whether it worked."""
    if not system.shortcut_exists(name):
        message = f"The shortcut \"{name}\" was not found. Create it in the Shortcuts app with exactly this name."
    elif system.run_shortcut(name):
        message = f"\"{name}\" worked."
    else:
        message = f"\"{name}\" exists but did not run. Open it in the Shortcuts app and check its action."
    answer = system.ask(message, ["Open setup guide", "OK"], default_button="OK", timeout_seconds=timeout_seconds)
    if answer == "Open setup guide":
        system.open_url(SHORTCUTS_GUIDE.as_uri())


def shortcuts_step(system, config, timeout_seconds: int) -> None:
    """Explain the two Shortcuts and let the user test them until they press Continue."""
    shortcut_on, shortcut_off = config.get("dnd.shortcut_on"), config.get("dnd.shortcut_off")
    text = SHORTCUTS_TEXT.format(on=shortcut_on, off=shortcut_off)
    while True:
        answer = system.ask(text, ["Test Focus On", "Test Focus Off", "Continue"], default_button="Continue", timeout_seconds=timeout_seconds)
        if answer == "Test Focus On":
            test_shortcut(system, shortcut_on, timeout_seconds)
        elif answer == "Test Focus Off":
            test_shortcut(system, shortcut_off, timeout_seconds)
        else:
            return


def run_onboarding(system, storage, config) -> bool:
    """
    The whole first-launch flow.

    In:  platform module, storage, config.
    Out: True if setup finished and consent for activity counts was given; False to quit.
    """
    timeout_seconds = config.get("dialogs.onboarding_timeout_seconds")
    if not welcome_step(system, timeout_seconds):
        return False
    choices = ask_consent_choices(system, timeout_seconds)
    if choices is None or not choices.get("activity_counts"):
        system.notify("Commit", "Commit needs permission to count activity to work. Nothing was saved.")
        return False
    save_consent(storage, choices)
    permissions_step(system, timeout_seconds)
    shortcuts_step(system, config, timeout_seconds)
    system.ask(ALLOWLIST_TEXT, ["OK"], timeout_seconds=timeout_seconds)
    storage.set_setting(ONBOARDING_KEY, True)
    system.notify("Commit", CALIBRATION_TEXT)
    return True


def has_valid_consent(storage) -> bool:
    """True if onboarding finished and activity counting is consented."""
    consent = storage.get_setting(CONSENT_KEY)
    return bool(storage.get_setting(ONBOARDING_KEY)) and bool(consent and consent["choices"].get("activity_counts"))
