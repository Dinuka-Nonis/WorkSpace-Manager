"""Spotlight naming prompt - FIXED."""

import tkinter as tk
from typing import Callable


class SpotlightPrompt:
    def __init__(self, desktop_id: str, on_confirm: Callable, on_cancel: Callable):
        self.desktop_id = desktop_id
        self.on_confirm = on_confirm
        self.on_cancel = on_cancel
        self._destroyed = False
        self._build()

    def _build(self):
        self.root = tk.Toplevel()
        self.root.title("")
        self.root.overrideredirect(True)
        self.root.attributes("-topmost", True)
        self.root.configure(bg="#111118")

        sw = self.root.winfo_screenwidth()
        sh = self.root.winfo_screenheight()
        w, h = 600, 100
        x = (sw - w) // 2
        y = int(sh * 0.22)
        self.root.geometry(f"{w}x{h}+{x}+{y}")

        # Main frame
        frame = tk.Frame(self.root, bg="#111118", padx=16, pady=16)
        frame.pack(fill="x")

        # Icon
        tk.Label(
            frame, text="🗂", font=("Arial", 18), 
            bg="#7c6af7", fg="white", width=2
        ).pack(side="left", padx=(0, 12))

        # Entry
        self.var = tk.StringVar()
        self.entry = tk.Entry(
            frame, textvariable=self.var, 
            font=("Arial", 15), 
            bg="#1a1a24", fg="white", 
            insertbackground="#a78bfa", 
            relief="solid", bd=1
        )
        self.entry.pack(side="left", fill="x", expand=True)
        self.entry.focus_set()

        # Hint bar
        hint = tk.Frame(self.root, bg="#1a1a24", padx=14, pady=6)
        hint.pack(fill="x")
        tk.Label(
            hint, text="↵ Enter to save  |  Esc to cancel", 
            font=("Arial", 9), bg="#1a1a24", fg="#6b6b80"
        ).pack()

        # Bindings
        self.root.bind("<Return>", lambda e: self._confirm())
        self.root.bind("<Escape>", lambda e: self._cancel())
        
        # Auto-dismiss after 30 seconds
        self.root.after(30000, self._cancel)

    def _confirm(self):
        if self._destroyed:
            return
            
        name = self.var.get().strip()
        if not name:
            return  # Don't allow empty names
            
        self._destroyed = True
        self.root.destroy()
        self.on_confirm(name, self.desktop_id)

    def _cancel(self):
        if self._destroyed:
            return
            
        self._destroyed = True
        self.root.destroy()
        self.on_cancel(self.desktop_id)