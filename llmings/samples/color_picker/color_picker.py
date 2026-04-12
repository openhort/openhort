"""Color Picker — pure client-side llming with vault persistence."""

from hort.llming import Llming


class ColorPicker(Llming):
    def activate(self, config: dict) -> None:
        self.log.info("Color picker activated")
