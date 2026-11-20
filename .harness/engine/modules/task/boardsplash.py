"""The start window of Start Harness (1.8.11): a small window without a frame, like the one a game shows while it loads, in place of the wheel in the terminal.

It shows the stage of `boardbg.background` and the seconds, and closes by itself once a paired page is open. A start that fails stays on screen with the reason and a Close button.
Tk runs on the main thread; the launcher's wait runs on another and talks to it through a queue only. On Windows the console window of `Start Harness.cmd` is hidden while the window shows, and shown
again when the start failed, so its `pause` can be seen. No tkinter, or no screen: `open_window` returns None and the terminal wheel is used. Stdlib only.
"""

from __future__ import annotations

import os
import queue
from pathlib import Path
from typing import Any, Optional

from core import messages

ICON = Path(__file__).resolve().parent / "web" / "icon.png"
WIDTH, HEIGHT = 420, 150
READY_MS = 1200  # how long "ready" stays before the window closes
TICK_MS = 40  # the bar moves this often
BG, INK, SOFT, ACCENT, TRACK, BAD, WARN, EDGE = "#101113", "#f5f6f7", "#a0a4ad", "#5ac8fa", "#24262a", "#ff6b6b", "#f5c451", "#2a2c31"


def say(key: str, /, **values: Any) -> str:
    return messages.text(key, **values)


def console(show: bool) -> bool:
    """Hide or show the console window of this process (Windows). Whether there was one. Never fails: the window is a helper."""
    if os.name != "nt":
        return False
    try:
        import ctypes

        handle = ctypes.windll.kernel32.GetConsoleWindow()  # type: ignore[attr-defined]
        if not handle:
            return False
        ctypes.windll.user32.ShowWindow(handle, 5 if show else 0)  # type: ignore[attr-defined]
        return True
    except Exception:  # noqa: BLE001 - a helper
        return False


class Splash:
    """The window. `tick` and `end` may be called from any thread; `run` only from the one that made it."""

    def __init__(self, tk: Any, window: Any) -> None:
        self.tk = tk
        self.window = window
        self.events: "queue.Queue[tuple]" = queue.Queue()
        self.cancelled = False
        self.finished = False
        self.hid_console = False
        self.offset = 0
        self.moving = True
        self.build()

    # --- called by the wait (any thread)
    def tick(self, stage: str, seconds: int) -> None:
        self.events.put(("tick", stage, seconds))

    def end(self, text: str, kind: str = "ready") -> None:
        """`kind`: ready (closes by itself), warn (the board runs, but the page was not seen), failed (the board did not start)."""
        self.events.put(("end", text, kind))

    # --- the window (its own thread)
    def build(self) -> None:
        tk, w = self.tk, self.window
        w.overrideredirect(True)
        w.configure(bg=EDGE)  # a 1 px edge: the window's own colour, shown around the inner frame
        inner = tk.Frame(w, bg=BG)
        inner.pack(fill="both", expand=True, padx=1, pady=1)
        self.inner = inner
        try:
            w.attributes("-topmost", True)
        except Exception:  # noqa: BLE001
            pass
        left = (w.winfo_screenwidth() - WIDTH) // 2
        top = (w.winfo_screenheight() - HEIGHT) // 3
        w.geometry(f"{WIDTH}x{HEIGHT}+{left}+{top}")
        cross = tk.Label(inner, text="\u00d7", bg=BG, fg=SOFT, font=("Segoe UI", 12), cursor="hand2")
        cross.place(relx=1.0, x=-10, y=4, anchor="ne")
        cross.bind("<Button-1>", lambda _event: self.close())
        head = tk.Frame(inner, bg=BG)
        head.pack(fill="x", padx=22, pady=(20, 0))
        try:
            self.icon = tk.PhotoImage(file=str(ICON))
            if self.icon.width() > 48:
                self.icon = self.icon.subsample(max(1, self.icon.width() // 40))
            tk.Label(head, image=self.icon, bg=BG).pack(side="left", padx=(0, 12))
        except Exception:  # noqa: BLE001 - no icon is fine
            self.icon = None
        words = tk.Frame(head, bg=BG)
        words.pack(side="left", fill="x", expand=True)
        tk.Label(words, text="Harness", bg=BG, fg=INK, font=("Segoe UI", 15, "bold"), anchor="w").pack(fill="x")
        self.stage = tk.Label(words, text=say("serve.bg.starting"), bg=BG, fg=SOFT, font=("Segoe UI", 10), anchor="w")
        self.stage.pack(fill="x")
        self.bar = tk.Canvas(inner, height=4, bg=TRACK, highlightthickness=0, bd=0)
        self.bar.pack(fill="x", padx=22, pady=(18, 0))
        self.segment = self.bar.create_rectangle(0, 0, 0, 4, fill=ACCENT, width=0)
        low = tk.Frame(inner, bg=BG)
        low.pack(fill="x", padx=22, pady=(8, 0))
        self.note = tk.Label(low, text="", bg=BG, fg=SOFT, font=("Segoe UI", 9), anchor="w", justify="left", wraplength=WIDTH - 110)
        self.note.pack(side="left", fill="x", expand=True)
        self.clock = tk.Label(low, text="0 s", bg=BG, fg=SOFT, font=("Segoe UI", 9))
        self.clock.pack(side="right")
        self.button = tk.Label(inner, text=say("serve.splash.close"), bg=TRACK, fg=INK, font=("Segoe UI", 10), padx=14, pady=4, cursor="hand2")  # a label: a Tk button on macOS ignores the colours
        self.button.bind("<Button-1>", lambda _event: self.close())
        w.bind("<Escape>", lambda _event: self.close())
        w.after(60, w.focus_force)  # a window without a frame gets no focus by itself, and Esc needs it
        w.after(TICK_MS, self.step)

    def step(self) -> None:
        try:
            while True:
                event = self.events.get_nowait()
                if event[0] == "tick":
                    self.stage.configure(text=event[1])
                    self.clock.configure(text=f"{event[2]} s")
                else:
                    self.show_end(*event[1:])
        except queue.Empty:
            pass
        if self.moving:
            width = max(self.bar.winfo_width(), 1)
            size = width // 4
            self.offset = (self.offset + max(width // 90, 3)) % (width + size)
            self.bar.coords(self.segment, self.offset - size, 0, self.offset, 4)
        if not self.finished or self.moving:
            self.window.after(TICK_MS, self.step)

    def show_end(self, text: str, kind: str) -> None:
        self.finished = True
        self.moving = False
        self.clock.configure(text="")
        if kind == "ready":
            self.bar.coords(self.segment, 0, 0, self.bar.winfo_width(), 4)
            self.stage.configure(text=say("serve.splash.ready"), fg=INK)
            self.window.after(READY_MS, self.close)
            return
        colour = BAD if kind == "failed" else WARN
        self.bar.itemconfigure(self.segment, fill=colour)
        self.bar.coords(self.segment, 0, 0, self.bar.winfo_width(), 4)
        self.stage.configure(text=say("serve.splash.failed" if kind == "failed" else "serve.splash.warn"), fg=colour)
        self.note.configure(text=text, wraplength=WIDTH - 50)
        self.clock.pack_forget()
        self.button.pack(side="bottom", anchor="e", padx=22, pady=(0, 16))
        self.window.update_idletasks()
        self.window.geometry(f"{WIDTH}x{max(HEIGHT, self.inner.winfo_reqheight() + 2)}")
        if self.hid_console and kind == "failed":  # the launcher's pause, and the log lines, are there
            console(True)

    def close(self) -> None:
        if not self.finished:
            self.cancelled = True  # the board keeps running; only the wait ends
        try:
            self.window.destroy()
        except Exception:  # noqa: BLE001
            pass

    def run(self) -> None:
        self.hid_console = console(False)
        try:
            self.window.mainloop()
        finally:
            if self.hid_console and self.cancelled:
                console(True)


def open_window() -> Optional[Splash]:
    """The start window, or None when there is no tkinter or no screen to show it on."""
    try:
        import tkinter
    except Exception:  # noqa: BLE001 - not installed with this Python
        return None
    try:
        window = tkinter.Tk()
        window.title("Harness")
        return Splash(tkinter, window)
    except Exception:  # noqa: BLE001 - no display, or a broken Tk
        return None
