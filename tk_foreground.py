from __future__ import annotations

import platform
import tkinter as tk


def present_window(
    win: tk.Misc,
    *,
    parent: tk.Misc | None = None,
    repeat: bool = True,
    topmost_ms: int = 250,
) -> None:
    """Porta in primo piano una finestra Tk, con rinforzo Win32 su Windows."""

    def _once() -> None:
        try:
            if parent is not None:
                try:
                    parent.update_idletasks()
                except tk.TclError:
                    pass
            win.update_idletasks()
            _lift_tk_window(win, parent=parent)
            _present_win32_window(win)
            _temporary_topmost(win, topmost_ms=topmost_ms)
            try:
                win.focus_force()
            except tk.TclError:
                pass
        except Exception:
            pass

    _once()
    if not repeat:
        return
    for delay in (80, 250, 600):
        try:
            win.after(delay, _once)
        except tk.TclError:
            break


def _lift_tk_window(win: tk.Misc, *, parent: tk.Misc | None) -> None:
    try:
        parent_visible = False
        if parent is not None:
            try:
                parent_visible = bool(int(str(parent.winfo_viewable())))
            except (tk.TclError, TypeError, ValueError):
                parent_visible = False
        if parent_visible:
            win.lift(parent)
        else:
            win.lift()
    except tk.TclError:
        pass


def _temporary_topmost(win: tk.Misc, *, topmost_ms: int) -> None:
    if platform.system() not in ("Darwin", "Windows"):
        return
    try:
        win.attributes("-topmost", True)
        win.after(topmost_ms, lambda: _clear_topmost(win))
    except Exception:
        pass


def _clear_topmost(win: tk.Misc) -> None:
    try:
        win.attributes("-topmost", False)
    except Exception:
        pass


def _present_win32_window(win: tk.Misc) -> None:
    if platform.system() != "Windows":
        return
    try:
        import ctypes
        from ctypes import wintypes

        user32 = ctypes.windll.user32
        kernel32 = ctypes.windll.kernel32
        user32.IsWindow.argtypes = [wintypes.HWND]
        user32.IsWindow.restype = wintypes.BOOL
        user32.ShowWindow.argtypes = [wintypes.HWND, ctypes.c_int]
        user32.ShowWindow.restype = wintypes.BOOL
        user32.SetWindowPos.argtypes = [
            wintypes.HWND,
            wintypes.HWND,
            ctypes.c_int,
            ctypes.c_int,
            ctypes.c_int,
            ctypes.c_int,
            ctypes.c_uint,
        ]
        user32.SetWindowPos.restype = wintypes.BOOL
        user32.GetForegroundWindow.restype = wintypes.HWND
        user32.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.c_void_p]
        user32.GetWindowThreadProcessId.restype = wintypes.DWORD
        user32.AttachThreadInput.argtypes = [wintypes.DWORD, wintypes.DWORD, wintypes.BOOL]
        user32.AttachThreadInput.restype = wintypes.BOOL
        user32.BringWindowToTop.argtypes = [wintypes.HWND]
        user32.BringWindowToTop.restype = wintypes.BOOL
        user32.SetForegroundWindow.argtypes = [wintypes.HWND]
        user32.SetForegroundWindow.restype = wintypes.BOOL
        user32.SetFocus.argtypes = [wintypes.HWND]
        user32.SetFocus.restype = wintypes.HWND
        kernel32.GetCurrentThreadId.restype = wintypes.DWORD

        hwnd = int(win.winfo_id())
        if not hwnd or not user32.IsWindow(wintypes.HWND(hwnd)):
            return

        SW_SHOW = 5
        SW_RESTORE = 9
        HWND_TOPMOST = -1
        HWND_NOTOPMOST = -2
        SWP_NOSIZE = 0x0001
        SWP_NOMOVE = 0x0002
        SWP_SHOWWINDOW = 0x0040
        flags = SWP_NOMOVE | SWP_NOSIZE | SWP_SHOWWINDOW

        try:
            tk_state = str(win.state())
        except Exception:
            tk_state = ""
        user32.ShowWindow(wintypes.HWND(hwnd), SW_RESTORE if tk_state == "iconic" else SW_SHOW)
        user32.SetWindowPos(wintypes.HWND(hwnd), wintypes.HWND(HWND_TOPMOST), 0, 0, 0, 0, flags)
        user32.SetWindowPos(wintypes.HWND(hwnd), wintypes.HWND(HWND_NOTOPMOST), 0, 0, 0, 0, flags)

        foreground = user32.GetForegroundWindow()
        current_tid = kernel32.GetCurrentThreadId()
        foreground_tid = user32.GetWindowThreadProcessId(wintypes.HWND(foreground), None) if foreground else 0
        attached = False
        if foreground_tid and foreground_tid != current_tid:
            attached = bool(user32.AttachThreadInput(current_tid, foreground_tid, True))
        try:
            user32.BringWindowToTop(wintypes.HWND(hwnd))
            user32.SetForegroundWindow(wintypes.HWND(hwnd))
            user32.SetFocus(wintypes.HWND(hwnd))
        finally:
            if attached:
                user32.AttachThreadInput(current_tid, foreground_tid, False)
    except Exception:
        pass
