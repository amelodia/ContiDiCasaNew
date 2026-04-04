"""
Secondi trascorsi dall'ultimo avvio del sistema operativo (uptime), per euristiche all'avvio app.
"""
from __future__ import annotations

import platform
import re
import shutil
import subprocess
import time
from pathlib import Path


def seconds_since_os_boot() -> float | None:
    """
    Uptime in secondi dall'ultimo boot. ``None`` se non determinabile su questa piattaforma.
    """
    system = platform.system()
    if system == "Darwin":
        return _seconds_since_boot_macos()
    if system == "Linux":
        return _seconds_since_boot_linux()
    if system == "Windows":
        return _seconds_since_boot_windows()
    return None


def _seconds_since_boot_macos() -> float | None:
    try:
        sysctl = shutil.which("sysctl") or "/usr/sbin/sysctl"
        out = subprocess.run(
            [sysctl, "-n", "kern.boottime"],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
        if out.returncode != 0 or not (out.stdout or "").strip():
            return None
        # Formato tipico: { sec = 1700000000, usec = 0 }
        m = re.search(r"sec\s*=\s*(\d+)", out.stdout)
        if not m:
            return None
        boot_sec = int(m.group(1))
        return max(0.0, time.time() - boot_sec)
    except (OSError, subprocess.TimeoutExpired, ValueError):
        return None


def _seconds_since_boot_linux() -> float | None:
    try:
        raw = Path("/proc/uptime").read_text(encoding="utf-8")
        return float(raw.split()[0])
    except Exception:
        return None


def _seconds_since_boot_windows() -> float | None:
    try:
        import ctypes

        k = ctypes.windll.kernel32
        k.GetTickCount64.argtypes = ()
        k.GetTickCount64.restype = ctypes.c_uint64
        return float(k.GetTickCount64()) / 1000.0
    except Exception:
        return None
