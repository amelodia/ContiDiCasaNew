"""
Attesa sincronizzazione file in cartelle Dropbox (e analoghe) prima della lettura del database.

Dropbox aggiorna i file a pezzi durante il download: dimensione e data di modifica cambiano finché
la copia locale non è completa. Aspettare che (dimensione, mtime) restino invariati per un intervallo
minimo riduce il rischio di aprire un .enc incompleto e generare conflitti o errori di decrittazione.
"""
from __future__ import annotations

import os
import sys
import time
from collections.abc import Sequence
from pathlib import Path

# Durata minima in cui size+mtime devono restare invariati (secondi).
_DEFAULT_STABLE_SECONDS = 1.6
# Intervallo tra due controlli (secondi).
_DEFAULT_POLL_SECONDS = 0.25
# Limite massimo di attesa totale per file (secondi) dopo che il file esiste (stabilità size/mtime).
_DEFAULT_MAX_WAIT_SECONDS = 180.0
# Se il file non esiste ancora (es. path errato dopo spostamento cartella): non usare 180s per «aspetta comparsa».
_DEFAULT_MAX_WAIT_EXISTENCE_SECONDS = 12.0
# Se il file non è stato modificato da almeno così tanti secondi, salta l’attesa di stabilità
# (tipico avvio quotidiano: niente download Dropbox in corso → niente splash né messaggi stderr).
_DEFAULT_SKIP_STABILITY_IF_UNMODIFIED_SEC = 45.0
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


def _skip_stability_if_unmodified_seconds() -> float:
    """Se ``CONTI_DROPBOX_SKIP_STABILITY_IF_UNMODIFIED_SEC=N`` con N>0, file non toccato da N secondi → niente attesa."""
    raw = os.environ.get("CONTI_DROPBOX_SKIP_STABILITY_IF_UNMODIFIED_SEC", "").strip()
    if raw:
        try:
            v = float(raw)
            return max(0.0, v)
        except ValueError:
            pass
    return _DEFAULT_SKIP_STABILITY_IF_UNMODIFIED_SEC


def _max_wait_existence_seconds() -> float:
    """Override: ``CONTI_CLOUD_WAIT_EXISTENCE_SECONDS`` (secondi, minimo 1)."""
    raw = os.environ.get("CONTI_CLOUD_WAIT_EXISTENCE_SECONDS", "").strip()
    if raw:
        try:
            return max(1.0, float(raw))
        except ValueError:
            pass
    return _DEFAULT_MAX_WAIT_EXISTENCE_SECONDS


def _close_splash_safe(splash: object | None) -> None:
    if splash is None:
        return
    aid = getattr(splash, "_conti_dropbox_splash_after", None)
    if aid is not None:
        try:
            splash.after_cancel(aid)  # type: ignore[attr-defined]
        except Exception:
            pass
        try:
            delattr(splash, "_conti_dropbox_splash_after")
        except Exception:
            pass
    try:
        splash.destroy()  # type: ignore[attr-defined]
    except Exception:
        pass


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
    max_wait_for_existence_seconds: float,
    ui_parent: object | None,
    label: str,
    batch_splash_holder: list[object | None] | None = None,
) -> float:
    """Attende che il file esista (finestra breve), poi che (size, mtime) siano stabili.

    Se il file non compare entro ``max_wait_for_existence_seconds`` (path errato o cartella
    spostata), termina senza attendere i ``max_wait_seconds`` pieni per la sola «comparsa».
    """
    t_start = time.monotonic()
    overall_deadline = t_start + max_wait_seconds
    existence_deadline = t_start + min(max_wait_for_existence_seconds, max_wait_seconds)
    splash = None
    last_log = t_start
    batch_mode = batch_splash_holder is not None

    def _ensure_splash() -> None:
        nonlocal splash
        if ui_parent is None:
            return
        if time.monotonic() - t_start < _SPLASH_AFTER_SECONDS:
            return
        if batch_mode:
            if batch_splash_holder is not None and batch_splash_holder[0] is None:
                batch_splash_holder[0] = _open_splash(
                    ui_parent,
                    "Verifica dei file nella cartella Dropbox…",
                )
            splash = batch_splash_holder[0] if batch_splash_holder else None
        else:
            if splash is None:
                splash = _open_splash(ui_parent, label)

    # Fase 1: comparsa file (Dropbox in download, ecc.) — timeout breve se il path non è più valido.
    while not path.exists():
        if time.monotonic() >= existence_deadline:
            if not batch_mode:
                _close_splash_safe(splash)
            return time.monotonic() - t_start
        if ui_parent is not None:
            _ensure_splash()
        if ui_parent is not None:
            _pump_ui(ui_parent)
        time.sleep(poll_seconds)

    fp0 = _stat_fingerprint(path)
    if fp0 is None:
        if not batch_mode:
            _close_splash_safe(splash)
        return time.monotonic() - t_start

    thresh = _skip_stability_if_unmodified_seconds()
    if thresh > 0:
        try:
            mtime = path.stat().st_mtime
            if time.time() - mtime >= thresh:
                if not batch_mode:
                    _close_splash_safe(splash)
                return time.monotonic() - t_start
        except OSError:
            pass

    stable_since = time.monotonic()

    # Fase 2: stabilità mentre Dropbox completa il file (può richiedere fino a max_wait_seconds dal t_start).
    while time.monotonic() < overall_deadline:
        if ui_parent is not None:
            _ensure_splash()

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

    if not batch_mode:
        _close_splash_safe(splash)
    return time.monotonic() - t_start


def _open_splash(parent: object, subtitle: str) -> object:
    import tkinter as tk

    w = tk.Toplevel(parent)  # type: ignore[call-overload]
    w.title("Conti di casa")
    # Niente transient: su macOS può lasciare una cornice vuota accanto alla finestra principale.
    try:
        w.withdraw()
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
        ww = max(w.winfo_reqwidth(), 320)
        wh = max(w.winfo_reqheight(), 1)
        sw = w.winfo_screenwidth()
        sh = w.winfo_screenheight()
        x = max(0, (sw - ww) // 2)
        y = max(0, (sh - wh) // 2)
        w.geometry(f"{ww}x{wh}+{x}+{y}")
        w.deiconify()
        w.lift()
        w.attributes("-topmost", True)

        def _topmost_off() -> None:
            try:
                if not w.winfo_exists():
                    return
                w.attributes("-topmost", False)
            except Exception:
                pass

        w._conti_dropbox_splash_after = w.after(400, _topmost_off)  # type: ignore[attr-defined]
    except Exception:
        try:
            w.destroy()
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
    Percorsi non Dropbox vengono ignorati.

    Se il file **non esiste** (es. dati spostati in un'altra cartella ma l'app punta ancora al path
    vecchio), l'attesa per la comparsa è limitata a pochi secondi (default 12s), non ai ``max_wait_seconds``
    pieni, così l'avvio non resta bloccato minuti sul dialog «Sincronizzazione…».

    Variabili d'ambiente (opzionali):

    - ``CONTI_SKIP_CLOUD_SYNC_WAIT=1`` — salta del tutto l'attesa (solo sviluppo / percorsi noti stabili).
    - ``CONTI_VERBOSE_CLOUD_WAIT=1`` — stampa su stderr all'inizio del controllo per ogni file Dropbox.
    - ``CONTI_CLOUD_WAIT_EXISTENCE_SECONDS`` — secondi massimi di attesa se il file non esiste ancora (default 12).
    - ``CONTI_DROPBOX_SKIP_STABILITY_IF_UNMODIFIED_SEC`` — se il file esiste ed è invariato da almeno N secondi (default 45),
      non attendere la finestra di stabilità (evita dialog e log a ogni avvio). Imposta ``0`` per comportamento precedente.
    """
    if os.environ.get("CONTI_SKIP_CLOUD_SYNC_WAIT", "").strip().lower() in ("1", "true", "yes", "on"):
        return
    verbose = os.environ.get("CONTI_VERBOSE_CLOUD_WAIT", "").strip().lower() in ("1", "true", "yes", "on")
    existence_cap = _max_wait_existence_seconds()
    seen: set[Path] = set()
    drop_paths: list[Path] = []
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
        drop_paths.append(p)

    batch_splash: list[object | None] = [None]
    try:
        for p in drop_paths:
            label = f"File: {p.name}"
            if verbose:
                print(
                    f"Verifica sincronizzazione Dropbox prima dell'apertura: {p}",
                    file=sys.stderr,
                )
            waited = _wait_file_stable(
                p,
                stable_seconds=stable_seconds,
                poll_seconds=poll_seconds,
                max_wait_seconds=max_wait_seconds,
                max_wait_for_existence_seconds=existence_cap,
                ui_parent=ui_parent,
                label=label,
                batch_splash_holder=batch_splash if len(drop_paths) > 1 else None,
            )
            if waited >= 8.0 and not verbose:
                print(
                    f"Attesa sincronizzazione Dropbox ({waited:.1f}s) prima dell'apertura: {p}",
                    file=sys.stderr,
                )
    finally:
        _close_splash_safe(batch_splash[0])
