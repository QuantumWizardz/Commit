"""
agent/menubar.py — the menu-bar icon (README module M1.10), built with rumps.

Title shows the state: Calm / Interrupted / Pressured / Paused / Learning.
Menu: Current load score · Pause tracking · Resume · Open dashboard · Settings ▸ ·
      Delete all my data · Quit.

The menu runs on the main thread. Long work (dialogs, the minute loop) happens elsewhere.
"""

from __future__ import annotations

import rumps
from PyObjCTools import AppHelper

from agent import consent, keychain
from agent.platform import system
from server.app import get_or_create_token

REFRESH_SECONDS = 5   # how often the title and load score are updated
PAIRING_TEXT = ("Copy this pairing token into the Commit Chrome extension "
                "(click the extension's icon → Pairing token → Save).")
CATEGORISER_MODES = [("off", "Off"), ("rules", "Rules only"), ("local", "Local AI (Ollama)"), ("api", "My own API key")]


class CommitMenuBar(rumps.App):
    """The menu-bar app. All actions call methods of the CommitAgent."""

    def __init__(self, agent):
        super().__init__("Commit", title="Commit", quit_button=None)
        self.agent = agent
        # The dashboard's "Delete all my data" runs on a server thread; the app must quit on the main thread.
        self.agent.request_quit = lambda: AppHelper.callAfter(rumps.quit_application)

        self.load_item = rumps.MenuItem("Current load score: –")
        self.pause_item = rumps.MenuItem("Pause tracking", callback=self.on_pause)
        self.resume_item = rumps.MenuItem("Resume", callback=self.on_resume)
        self.dnd_ask_item = rumps.MenuItem("Do Not Disturb: ask first", callback=self.on_dnd_ask)
        self.dnd_auto_item = rumps.MenuItem("Do Not Disturb: always automatic", callback=self.on_dnd_auto)
        self.checkins_item = rumps.MenuItem("Load check-ins", callback=self.on_toggle_checkins)

        # Website categories: one checkable item per categoriser mode.
        self.mode_items = {}
        categories_menu = rumps.MenuItem("Website categories")
        for mode, label in CATEGORISER_MODES:
            item = rumps.MenuItem(label, callback=self.on_categoriser_mode)
            self.mode_items[mode] = item
            categories_menu.add(item)
        for item in [
            None,
            rumps.MenuItem("AI model…", callback=self.on_model_settings),
            rumps.MenuItem("Set API key…", callback=self.on_set_api_key),
            rumps.MenuItem("Test AI connection", callback=self.on_test_ai),
        ]:
            categories_menu.add(item if item is not None else rumps.separator)

        settings_menu = rumps.MenuItem("Settings")
        for item in [
            self.dnd_ask_item,
            self.dnd_auto_item,
            self.checkins_item,
            None,
            categories_menu,
            rumps.MenuItem("Extension pairing token…", callback=self.on_pairing_token),
            None,
            rumps.MenuItem("Re-run calibration", callback=self.on_recalibrate),
            rumps.MenuItem("Consent choices…", callback=self.on_consent),
            rumps.MenuItem("Do Not Disturb setup…", callback=self.on_shortcuts_setup),
            rumps.MenuItem("Privacy policy", callback=self.on_privacy_policy),
        ]:
            settings_menu.add(item if item is not None else rumps.separator)

        self.menu = [
            self.load_item,
            None,
            self.pause_item,
            self.resume_item,
            rumps.MenuItem("Open dashboard", callback=self.on_open_dashboard),
            rumps.MenuItem("Weekly report (PDF)", callback=self.on_weekly_report),
            settings_menu,
            None,
            rumps.MenuItem("Delete all my data", callback=self.on_delete),
            rumps.MenuItem("Quit", callback=self.on_quit),
        ]
        self.timer = rumps.Timer(self.refresh, REFRESH_SECONDS)
        self.timer.start()
        self.refresh(None)

    # ------------------------------------------------------------ display

    def refresh(self, _sender) -> None:
        """Update the title, load score, and which items are enabled/checked."""
        status = self.agent.engine.status
        self.title = f"Commit · {status['state']}"
        score = status["load_score"]
        self.load_item.title = f"Current load score: {score:.0f}" if score is not None else "Current load score: –"

        paused = self.agent.engine.paused
        # rumps shows an item greyed out when it has no callback.
        self.pause_item.set_callback(None if paused else self.on_pause)
        self.resume_item.set_callback(self.on_resume if paused else None)

        auto = self.agent.config.get("dnd.mode") == "auto"
        self.dnd_ask_item.state = int(not auto)
        self.dnd_auto_item.state = int(auto)
        self.checkins_item.state = int(self.checkins_enabled())
        current_mode = self.agent.config.get("categoriser.mode")
        for mode, item in self.mode_items.items():
            item.state = int(mode == current_mode)

    def checkins_enabled(self) -> bool:
        """Check-ins run only when switched on AND consented."""
        choices = self.agent.storage.get_setting(consent.CONSENT_KEY, {}).get("choices", {})
        return bool(self.agent.config.get("checkins.enabled") and choices.get("checkins"))

    # ------------------------------------------------------------ menu callbacks

    def on_pause(self, _sender) -> None:
        self.agent.pause()
        self.refresh(None)

    def on_resume(self, _sender) -> None:
        self.agent.resume()
        self.refresh(None)

    def on_open_dashboard(self, _sender) -> None:
        system.open_url(self.agent.dashboard_url())

    def on_dnd_ask(self, _sender) -> None:
        self.agent.config.set("dnd.mode", "ask")
        self.refresh(None)

    def on_dnd_auto(self, _sender) -> None:
        self.agent.config.set("dnd.mode", "auto")
        self.refresh(None)

    def on_toggle_checkins(self, _sender) -> None:
        """Turning check-ins on also records consent for them (switch 5)."""
        turn_on = not self.checkins_enabled()
        self.agent.config.set("checkins.enabled", turn_on)
        saved = self.agent.storage.get_setting(consent.CONSENT_KEY)
        saved["choices"]["checkins"] = turn_on
        consent.save_consent(self.agent.storage, saved["choices"])
        self.refresh(None)

    def on_recalibrate(self, _sender) -> None:
        self.agent.engine.restart_calibration()
        system.notify("Commit", consent.CALIBRATION_TEXT)
        self.refresh(None)

    def on_consent(self, _sender) -> None:
        """Ask the consent questions again. Withdrawing the required one stops Commit."""
        choices = consent.ask_consent_choices(system, self.agent.config.get("dialogs.onboarding_timeout_seconds"))
        if choices is None:
            return  # timed out: keep the previous choices
        if not choices.get("activity_counts"):
            # Record the withdrawal; next launch starts the consent flow again.
            consent.save_consent(self.agent.storage, choices)
            self.agent.storage.set_setting(consent.ONBOARDING_KEY, False)
            system.notify("Commit", "Commit has stopped. Your stored data is kept until you delete it or it expires.")
            self.on_quit(None)
            return
        consent.save_consent(self.agent.storage, choices)
        self.refresh(None)

    def on_shortcuts_setup(self, _sender) -> None:
        consent.shortcuts_step(system, self.agent.config, self.agent.config.get("dialogs.onboarding_timeout_seconds"))

    def on_privacy_policy(self, _sender) -> None:
        system.open_url(consent.PRIVACY_POLICY.as_uri())

    # ------------------------------------------------------------ Phase 2: websites and report

    def on_weekly_report(self, _sender) -> None:
        self.agent.open_weekly_report()

    def on_pairing_token(self, _sender) -> None:
        """Show the token so the user can copy it into the Chrome extension (README 9.2)."""
        token = get_or_create_token(self.agent.storage)
        system.ask_text(PAIRING_TEXT, default_text=token, timeout_seconds=self.timeout())

    def ensure_title_consent(self, consent_key: str) -> bool:
        """Local AI needs consent switch 3, API key mode switch 4. Ask now if it was not given."""
        saved = self.agent.storage.get_setting(consent.CONSENT_KEY)
        if saved["choices"].get(consent_key):
            return True
        title, explanation = next((t, e) for key, t, e, _, _ in consent.CONSENT_ITEMS if key == consent_key)
        answer = system.ask(f"{title}\n\n{explanation}\n\nAllow this?", ["No", "Yes"], default_button="No", timeout_seconds=self.timeout())
        if answer != "Yes":
            return False
        saved["choices"][consent_key] = True
        consent.save_consent(self.agent.storage, saved["choices"])
        return True

    def on_categoriser_mode(self, sender) -> None:
        mode = next(key for key, item in self.mode_items.items() if item is sender)
        consent_key = {"local": "title_local", "api": "title_api"}.get(mode)
        if consent_key is not None and not self.ensure_title_consent(consent_key):
            return
        self.agent.config.set("categoriser.mode", mode)
        if mode == "api" and not keychain.get_api_key():
            system.notify("Commit", "Now add your key: Settings → Website categories → Set API key…")
        self.refresh(None)

    def on_model_settings(self, _sender) -> None:
        """Change the model name (and, for API mode, the OpenAI-compatible address)."""
        mode = self.agent.config.get("categoriser.mode")
        if mode not in ("local", "api"):
            system.notify("Commit", "Choose Local AI or My own API key first.")
            return
        settings = self.agent.config.get(f"categoriser.{mode}")
        if mode == "api":
            base_url = system.ask_text("API address (any OpenAI-compatible endpoint):", settings["base_url"], timeout_seconds=self.timeout())
            if base_url is None:
                return
            settings["base_url"] = base_url.strip()
        model = system.ask_text("Model name (for Ollama, see `ollama list`):", settings["model"], timeout_seconds=self.timeout())
        if model is None:
            return
        settings["model"] = model.strip()
        self.agent.config.set(f"categoriser.{mode}", settings)

    def on_set_api_key(self, _sender) -> None:
        """Type the API key; it is saved only in the macOS Keychain (P8)."""
        api_key = system.ask_text("Paste your API key. It is stored only in the macOS Keychain.", hidden=True, timeout_seconds=self.timeout())
        if api_key:
            keychain.set_api_key(api_key.strip())
            system.notify("Commit", "API key saved in the Keychain.")

    def on_test_ai(self, _sender) -> None:
        _, message = self.agent.categoriser.test_connection()
        system.ask(message, ["OK"], timeout_seconds=self.timeout())

    def timeout(self) -> int:
        return self.agent.config.get("dialogs.onboarding_timeout_seconds")

    def on_delete(self, _sender) -> None:
        if self.agent.confirm_and_delete_all_data():
            rumps.quit_application()

    def on_quit(self, _sender) -> None:
        self.agent.quit()
        rumps.quit_application()
