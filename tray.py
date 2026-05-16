import pystray
from PIL import Image, ImageDraw

from config import _resource


class Tray:
    def __init__(self, app):
        self.app = app
        self.icon = None

    def make_image(self):
        icon_path = _resource("tray_icon.png")
        if icon_path.exists():
            return Image.open(icon_path).convert("RGBA")
        # Fallback: generiertes Icon
        image = Image.new("RGB", (64, 64), "black")
        draw = ImageDraw.Draw(image)
        draw.ellipse((12, 8, 52, 48), fill="white")
        draw.rectangle((28, 42, 36, 56), fill="white")
        draw.rectangle((20, 54, 44, 60), fill="white")
        return image

    def run(self):
        menu = pystray.Menu(
            pystray.MenuItem("Settings", lambda: self.app.open_settings()),
            pystray.MenuItem("Quit", lambda: self.app.quit()),
        )
        self.icon = pystray.Icon(
            "EuroWisprFlow", self.make_image(), "EuroWisprFlow", menu
        )
        self.icon.run()

    def stop(self):
        if self.icon:
            self.icon.stop()
