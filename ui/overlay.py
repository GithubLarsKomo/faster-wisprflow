import tkinter as tk

from config import _resource
from ui.utils import _target_monitor


class Overlay:
    def __init__(self):
        self.root = tk.Tk()
        self.root.title("EuroWisprFlow")
        self.root.overrideredirect(True)
        self.root.attributes("-topmost", True)
        self.root.attributes("-alpha", 0.92)

        self.label = tk.Label(
            self.root,
            text="Bereit",
            font=("Segoe UI", 18),
            bg="white",
            fg="#2a671b",
            padx=24,
            pady=14,
        )
        self.root.configure(bg="white")
        self.label.pack()

        icon_path = _resource("tray_icon.png")
        if icon_path.exists():
            try:
                img = tk.PhotoImage(file=str(icon_path))
                self.root.iconphoto(True, img)
            except Exception:
                pass

        self.root.withdraw()

    def show(self, text):
        self.label.config(text=text)
        self.root.update_idletasks()
        width = self.root.winfo_reqwidth()
        height = self.root.winfo_reqheight()
        ml, mt, mr, mb = _target_monitor()
        x = ml + (mr - ml - width) // 2
        y = mb - height - 60
        self.root.geometry(f"+{x}+{y}")
        self.root.deiconify()
        self.root.update()

    def set_text(self, text):
        self.label.config(text=text)
        self.root.update()

    def hide(self):
        self.root.withdraw()
        self.root.update()

    def loop(self):
        self.root.mainloop()
