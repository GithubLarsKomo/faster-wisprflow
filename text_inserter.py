import time

import keyboard
import pyperclip

from config import Config


class TextInserter:
    def __init__(self, config: Config):
        self.config = config

    def insert_text(self, text):
        if not text:
            return

        old_clipboard = None
        if self.config.restore_clipboard:
            try:
                old_clipboard = pyperclip.paste()
            except Exception:
                pass

        pyperclip.copy(text)
        time.sleep(0.08)
        keyboard.press_and_release("ctrl+v")
        time.sleep(0.15)

        if self.config.restore_clipboard and old_clipboard is not None:
            pyperclip.copy(old_clipboard)
