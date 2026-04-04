"""
Attesa sincronizzazione file in cartelle Dropbox (e analoghe) prima della lettura del database.

Dropbox aggiorna i file a pezzi durante il download: dimensione e data di modifica cambiano finché
la copia locale non è completa. Aspettare che (dimensione, mtime) restino invariati per un intervallo
minimo riduce il rischio di aprire un .enc incompleto e generare conflitti o errori di decrittazione.
"""
from __future__ import annotations

import sys
import time
from collections.abc import Sequence
from pathlib import Path

# Durata minima in cui size+mtime devono restare invariati (secondi).
_DEFAULT_STABLE_SECONDS = 1.6
# Intervallo tra due controlli (secondi).
_DEFAULT_POLL_SECONDS = 0.25
# Limite massimo di attesa totale per file (secondi).
_DEFAULT_MAX_WAIT_SECONDS = 180.0
# Dopo quanti secondi mostrare la finestrina Tk (se parent è disponibile).
_SPLASH_AFTER_SECONDS = 0.4


def path_looks_under_dropbox(path: Path) -> bool:
    """
    Euristica per percorsi macOS/Windows/Linux usati da Dropbox (cartella classica o CloudStorage).
    """
    try:
        cur = path.resolve(strict=False)
    except (OSError, TypeError):
        try:
            cur = path.resolve()
        except OSError:
            cur = path.absolute()
    p = cur
    while True:
        nm = p.name.lower()
        try:
            parent = p.parent
        except ValueError:
            break
        pn = parent.name.lower()
        if pn == "cloudstorage" and nm.startswith("dropbox"):
            return True
        if nm == "dropbox" or nm.startswith("dropbox-") or nm.startswith("dropbox ("):
            return True
        if p == parent:
            break
        p = parent
    return False


def _stat_fingerprint(path: Path) -> tuple[int, int] | None:
    try:
        st = path.stat()
    except OSError:
        return None
    mtime_ns = getattr(st, "st_mtime_ns", int(st.st_mtime * 1_000_000_000))
    return (st.st_size, mtime_ns)


def _wait_file_stable(
    path: Path,
    *,
    stable_seconds: float,
    poll_seconds: float,
    max_wait_seconds: float,
    ui_parent: object | None,
    label: str,
) -> None:
    """Attende finché il file esiste e (size, mtime) non cambiano per ``stable_seconds``."""
    t_start = time.monotonic()
    deadline = t_start + max_wait_seconds
    splash = None
    last_log = t_start

    # Fino a esistenza (es. primo avvio su nuova postazione: file in arrivo da Dropbox)
    while not path.exists():
        if time.monotonic() >= deadline:
            return
        if ui_parent is not None and splash is None and time.monotonic() - t_start >= _SPLASH_AFTER_SECONDS:
            splash = _open_splash(ui_parent, label)
        if ui_parent is not None:
            _pump_ui(ui_parent)
        time.sleep(poll_seconds)

    fp0 = _stat_fingerprint(path)
    if fp0 is None:
        return
    stable_since = time.monotonic()

    while time.monotonic() < deadline:
        if ui_parent is not None and splash is None and time.monotonic() - t_start >= _SPLASH_AFTER_SECONDS:
            splash = _open_splash(ui_parent, label)

        time.sleep(poll_seconds)
        if ui_parent is not None:
            _pump_ui(ui_parent)

        fp1 = _stat_fingerprint(path)
        if fp1 is None:
            stable_since = time.monotonic()
            continue
        if fp1 != fp0:
            fp0 = fp1
            stable_since = time.monotonic()
            if time.monotonic() - last_log >= 5.0:
                print(
                    f"Attesa sincronizzazione Dropbox su {path.name!r}…",
                    file=sys.stderr,
                )
                last_log = time.monotonic()
            continue
        if time.monotonic() - stable_since >= stable_seconds:
            break

    if splash is not None:
        try:
            splash.destroy()
        except Exception:
            pass


def _open_splash(parent: object, subtitle: str) -> object:
    import tkinter as tk

    w = tk.Toplevel(parent)  # type: ignore[call-overload]
    w.title("Conti di casa")
    try:
        w.transient(parent)  # type: ignore[attr-defined]
    except Exception:
        pass
    w.resizable(False, False)
    frm = tk.Frame(w, padx=22, pady=18)
    frm.pack()
    tk.Label(
        frm,
        text="Sincronizzazione dati in corso…",
        font=("TkDefaultFont", 12, "bold"),
    ).pack(anchor="w")
    tk.Label(
        frm,
        text=subtitle,
        font=("TkDefaultFont", 11),
        fg="#444444",
        wraplength=360,
        justify="left",
    ).pack(anchor="w", pady=(8, 0))
    tk.Label(
        frm,
        text="Attendere: Dropbox sta aggiornando i file in questa cartella.",
        font=("TkDefaultFont", 10),
        fg="#666666",
        wraplength=360,
        justify="left",
    ).pack(anchor="w", pady=(10, 0))
    try:
        w.update_idletasks()
        w.lift()
        w.attributes("-topmost", True)
        w.after(400, lambda: w.attributes("-topmost", False))
    except Exception:
        pass
    return w


def _pump_ui(parent: object) -> None:
    try:
        parent.update_idletasks()  # type: ignore[attr-defined]
        parent.update()  # type: ignore[attr-defined]
    except Exception:
        pass


def wait_for_paths_stable_if_cloud(
    paths: Sequence[Path],
    *,
    ui_parent: object | None = None,
    stable_seconds: float = _DEFAULT_STABLE_SECONDS,
    poll_seconds: float = _DEFAULT_POLL_SECONDS,
    max_wait_seconds: float = _DEFAULT_MAX_WAIT_SECONDS,
) -> None:
    """
    Per ogni percorso sotto Dropbox (euristica), attende che il file sia stabile prima che l'app lo legga.
    Percorsi non Dropbox vengono ignorati. File assenti dopo ``max_wait_seconds``: nessun blocco indefinito.
    """
    seen: set[Path] = set()
    for raw in paths:
        try:
            p = raw.resolve(strict=False)
        except (OSError, TypeError):
            p = raw
        if p in seen:
            continue
        seen.add(p)
        if not path_looks_under_dropbox(p):
            continue
        label = f"File: {p.name}"
        print(
            f"Verifica sincronizzazione Dropbox prima dell'apertura: {p}",
            file=sys.stderr,
        )
        _wait_file_stable(
            p,
            stable_seconds=stable_seconds,
            poll_seconds=poll_seconds,
            max_wait_seconds=max_wait_seconds,
            ui_parent=ui_parent,
            label=label,
        )
