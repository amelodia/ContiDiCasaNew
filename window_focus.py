from __future__ import annotations

import platform
import tkinter as tk


def present_window(win: tk.Misc, parent: tk.Misc | None = None, *, topmost_ms: int = 180) -> None:
    """Porta una finestra Tk davanti alle altre, in particolare nelle build Windows."""
    try:
        win.update_idletasks()
    except Exception:
        pass
    try:
        win.deiconify()
    except Exception:
        pass
    try:
        parent_visible = False
        if parent is not None:
            try:
                parent_visible = bool(int(str(parent.winfo_viewable())))
            except (tk.TclError, TypeError, ValueError):
                parent_visible = False
        if parent_visible and parent is not None:
            win.lift(parent)
        else:
            win.lift()
    except Exception:
        pass
    try:
        win.focus_force()
    except Exception:
        pass

    system = platform.system()
    if system in {"Windows", "Darwin"}:
        try:
            win.attributes("-topmost", True)
            win.after(topmost_ms, lambda: win.attributes("-topmost", False))
        except Exception:
            pass

    if system == "Windows":
        _present_window_win32(win)


def _present_window_win32(win: tk.Misc) -> None:
    try:
        import ctypes

        hwnd = int(win.winfo_id())
        user32 = ctypes.windll.user32
        if user32.IsIconic(hwnd):
            user32.ShowWindow(hwnd, 9)  # SW_RESTORE
        user32.SetForegroundWindow(hwnd)
    except Exception:
        pass
