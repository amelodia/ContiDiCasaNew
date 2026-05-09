from __future__ import annotations

import platform
import tkinter as tk


def present_window(
    win: tk.Misc,
    *,
    parent: tk.Misc | None = None,
    repeat: bool = True,
    topmost_ms: int = 2200,
) -> None:
    """Porta in primo piano una finestra Tk, con rinforzo Win32 su Windows."""

    def _once() -> None:
        try:
            if parent is not None:
                try:
                    parent.update_idletasks()
                except tk.TclError:
                    pass
            _ensure_tk_window_visible(win)
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
    for delay in (80, 250, 600, 1200):
        try:
            win.after(delay, _once)
        except tk.TclError:
            break


def _ensure_tk_window_visible(win: tk.Misc) -> None:
    try:
        state = str(win.state())
    except Exception:
        state = ""
    try:
        if state in ("withdrawn", "iconic"):
            win.deiconify()
    except tk.TclError:
        pass
    if platform.system() == "Windows" and state in ("withdrawn", "iconic"):
        try:
            win.state("normal")
        except tk.TclError:
            pass


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
        old_after = getattr(win, "_cdc_topmost_clear_after", None)
        if old_after is not None:
            try:
                win.after_cancel(old_after)
            except Exception:
                pass
        win.attributes("-topmost", True)
        after_id = win.after(topmost_ms, lambda: _clear_topmost(win))
        setattr(win, "_cdc_topmost_clear_after", after_id)
    except Exception:
        pass


def _clear_topmost(win: tk.Misc) -> None:
    try:
        setattr(win, "_cdc_topmost_clear_after", None)
        win.attributes("-topmost", False)
    except Exception:
        pass


def _tk_outer_hwnd(win: tk.Misc) -> int:
    candidates: list[object] = []
    try:
        # Su Windows il frame WM e il client Tk possono avere HWND diversi: per portare
        # davanti la finestra serve il frame esterno.
        candidates.append(win.tk.call("wm", "frame", win._w))  # type: ignore[attr-defined]
    except Exception:
        pass
    try:
        candidates.append(win.winfo_id())
    except Exception:
        pass
    for raw in candidates:
        try:
            text = str(raw).strip()
            if not text:
                continue
            return int(text, 0)
        except Exception:
            try:
                return int(raw)  # type: ignore[arg-type]
            except Exception:
                continue
    return 0


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
        user32.SetActiveWindow.argtypes = [wintypes.HWND]
        user32.SetActiveWindow.restype = wintypes.HWND
        user32.SetFocus.argtypes = [wintypes.HWND]
        user32.SetFocus.restype = wintypes.HWND
        user32.ShowWindowAsync.argtypes = [wintypes.HWND, ctypes.c_int]
        user32.ShowWindowAsync.restype = wintypes.BOOL
        user32.IsIconic.argtypes = [wintypes.HWND]
        user32.IsIconic.restype = wintypes.BOOL
        user32.keybd_event.argtypes = [wintypes.BYTE, wintypes.BYTE, wintypes.DWORD, ctypes.c_void_p]
        user32.keybd_event.restype = None
        kernel32.GetCurrentThreadId.restype = wintypes.DWORD

        hwnd = _tk_outer_hwnd(win)
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
        show_cmd = SW_RESTORE if tk_state == "iconic" or user32.IsIconic(wintypes.HWND(hwnd)) else SW_SHOW
        user32.ShowWindow(wintypes.HWND(hwnd), show_cmd)
        user32.ShowWindowAsync(wintypes.HWND(hwnd), show_cmd)
        user32.SetWindowPos(wintypes.HWND(hwnd), wintypes.HWND(HWND_TOPMOST), 0, 0, 0, 0, flags)
        user32.SetWindowPos(wintypes.HWND(hwnd), wintypes.HWND(HWND_NOTOPMOST), 0, 0, 0, 0, flags)

        foreground = user32.GetForegroundWindow()
        current_tid = kernel32.GetCurrentThreadId()
        target_tid = user32.GetWindowThreadProcessId(wintypes.HWND(hwnd), None)
        foreground_tid = user32.GetWindowThreadProcessId(wintypes.HWND(foreground), None) if foreground else 0
        attached: list[tuple[int, int]] = []

        def _attach(src: int, dst: int) -> None:
            if src and dst and src != dst and user32.AttachThreadInput(src, dst, True):
                attached.append((src, dst))

        _attach(current_tid, foreground_tid)
        _attach(target_tid, foreground_tid)
        try:
            VK_MENU = 0x12
            KEYEVENTF_KEYUP = 0x0002
            try:
                # Workaround noto: un evento Alt consente a SetForegroundWindow di
                # superare il foreground lock quando l'app e stata lanciata da Explorer.
                user32.keybd_event(VK_MENU, 0, 0, None)
                user32.keybd_event(VK_MENU, 0, KEYEVENTF_KEYUP, None)
            except Exception:
                pass
            try:
                user32.SwitchToThisWindow(wintypes.HWND(hwnd), True)
            except Exception:
                pass
            user32.BringWindowToTop(wintypes.HWND(hwnd))
            user32.SetActiveWindow(wintypes.HWND(hwnd))
            user32.SetForegroundWindow(wintypes.HWND(hwnd))
            user32.SetFocus(wintypes.HWND(hwnd))
        finally:
            for src, dst in reversed(attached):
                user32.AttachThreadInput(src, dst, False)
    except Exception:
        pass
