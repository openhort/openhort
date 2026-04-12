"""Pomodoro Timer — pure client-side llming.

No server-side logic needed. The timer runs in the browser.
Vault persistence keeps state across page reloads.
"""

from hort.llming import Llming


class Pomodoro(Llming):
    def activate(self, config: dict) -> None:
        self.log.info("Pomodoro timer activated")
