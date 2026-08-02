"""
Cartella dati configurabile dall'utente: contiene ``conti_di_casa.key``, i file ``.enc``,
la sottocartella ``legacy_import/`` (JSON unificato e bootstrap sessione).

Il percorso scelto è salvato in:
- macOS: ``~/Library/Application Support/ContiDiCasa/data_workspace.json``
- Windows: ``%APPDATA%\\ContiDiCasa\\data_workspace.json``
"""
from __future__ import annotations

import json
import os
import shutil
import sys
from pathlib import Path

_CONFIG_NAME = "data_workspace.json"

_workspace_root: Path | None = None


def app_install_dir() -> Path:
    """Directory dell'eseguibile (PyInstaller) o cwd in sviluppo."""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path.cwd().resolve()


def _visible_dialog_parent(parent) -> object | None:
    """Parent per dialoghi Tk: None se la root principale non è ancora mappata."""
    if parent is None:
        return None
    try:
        if bool(int(str(parent.winfo_viewable()))):
            return parent
    except Exception:
        pass
    return None


def _center_toplevel_on_screen(win) -> None:
    try:
        win.update_idletasks()
        ww = max(win.winfo_reqwidth(), 320)
        wh = max(win.winfo_reqheight(), 1)
        sw = win.winfo_screenwidth()
        sh = win.winfo_screenheight()
        win.geometry(f"{ww}x{wh}+{max(0, (sw - ww) // 2)}+{max(0, (sh - wh) // 2)}")
    except Exception:
        pass


def _iter_workspace_config_paths() -> list[Path]:
    """Percorsi noti del file di configurazione (Roaming, Local, accanto all'exe)."""
    paths: list[Path] = []
    seen: set[str] = set()

    def _add(p: Path) -> None:
        try:
            key = str(p.expanduser().resolve())
        except OSError:
            key = str(p)
        if key in seen:
            return
        seen.add(key)
        paths.append(p)

    _add(workspace_config_path())
    if sys.platform == "win32":
        local = (os.environ.get("LOCALAPPDATA") or "").strip()
        if local:
            _add(Path(local) / "ContiDiCasa" / _CONFIG_NAME)
        _add(app_install_dir() / _CONFIG_NAME)
    return paths


def _load_best_workspace_config() -> tuple[dict, Path | None]:
    best: dict = {}
    best_path: Path | None = None
    for p in _iter_workspace_config_paths():
        if not p.is_file():
            continue
        try:
            obj = json.loads(p.read_text(encoding="utf-8"))
            if not isinstance(obj, dict):
                continue
        except Exception:
            continue
        if obj.get("workspace_path") or obj.get("path"):
            return obj, p
        if not best:
            best = obj
            best_path = p
    return best, best_path


def _canonicalize_workspace_config(obj: dict, source: Path | None) -> None:
    """Copia in Roaming/Application Support la config trovata altrove (upgrade Windows)."""
    canonical = workspace_config_path()
    if source is not None:
        try:
            if source.resolve() == canonical.resolve():
                return
        except OSError:
            pass
    merged = {}
    try:
        cp = workspace_config_path()
        if cp.is_file():
            raw = json.loads(cp.read_text(encoding="utf-8"))
            if isinstance(raw, dict):
                merged.update(raw)
    except Exception:
        pass
    merged.update(obj)
    try:
        _write_workspace_config(merged)
    except Exception:
        pass


def app_support_dir() -> Path:
    if sys.platform == "win32":
        base = os.environ.get("APPDATA")
        if base:
            return Path(base) / "ContiDiCasa"
        return Path.home() / "AppData" / "Roaming" / "ContiDiCasa"
    return Path.home() / "Library" / "Application Support" / "ContiDiCasa"


def workspace_config_path() -> Path:
    return app_support_dir() / _CONFIG_NAME


def _read_workspace_config() -> dict:
    obj, _src = _load_best_workspace_config()
    return obj if isinstance(obj, dict) else {}


def _write_workspace_config(obj: dict) -> None:
    app_support_dir().mkdir(parents=True, exist_ok=True)
    workspace_config_path().write_text(
        json.dumps(obj, ensure_ascii=True, indent=2) + "\n",
        encoding="utf-8",
    )


def load_saved_workspace_path() -> Path | None:
    """Restituisce il percorso assoluto se la config indica una directory esistente."""
    obj, src = _load_best_workspace_config()
    raw = obj.get("workspace_path") or obj.get("path")
    if raw:
        try:
            path = Path(str(raw)).expanduser().resolve()
            if path.is_dir():
                _canonicalize_workspace_config(obj, src)
                return path
        except Exception:
            pass
    rediscovered = try_migrate_from_legacy_relative_data()
    if rediscovered is not None:
        save_workspace_path(rediscovered)
        _canonicalize_workspace_config({**obj, "workspace_path": str(rediscovered)}, src)
        return rediscovered
    return None


def _is_valid_data_dir(d: Path) -> bool:
    if not d.is_dir():
        return False
    if (d / "conti_di_casa.key").is_file():
        return True
    return any(is_workspace_primary_enc_file(p) for p in d.glob("*.enc"))


def candidate_legacy_data_dirs() -> list[Path]:
    """Cartelle ``data`` / Dropbox tipiche da versioni precedenti (portable, installer, dev)."""
    seen: set[str] = set()
    out: list[Path] = []

    def _add(raw: Path) -> None:
        try:
            p = raw.expanduser().resolve()
        except OSError:
            return
        key = str(p)
        if key in seen:
            return
        seen.add(key)
        out.append(p)

    _add(app_install_dir() / "data")
    _add(Path.cwd() / "data")
    if sys.platform == "win32":
        _add(app_support_dir())
        local = (os.environ.get("LOCALAPPDATA") or "").strip()
        if local:
            _add(Path(local) / "ContiDiCasa")
        _add(Path.home() / "Documents" / "ContiDiCasa")
        dropbox = Path.home() / "Dropbox"
        if dropbox.is_dir():
            _add(dropbox / "ContiDiCasa")
            _add(dropbox / "Conti di casa")
    return out


def save_workspace_path(path: Path) -> None:
    path = path.expanduser().resolve()
    obj = _read_workspace_config()
    obj["workspace_path"] = str(path)
    _write_workspace_config(obj)


def load_last_login_email() -> str | None:
    """Ultima email usata per l’accesso (persistente, indipendente dal profilo nel DB corrente)."""
    raw = _read_workspace_config().get("last_login_email")
    if not raw or not isinstance(raw, str):
        return None
    w = raw.strip().lower()
    return w if w else None


def save_last_login_email(email: str) -> None:
    obj = _read_workspace_config()
    obj["last_login_email"] = (email or "").strip().lower()
    _write_workspace_config(obj)


def set_data_workspace_root(path: Path) -> None:
    global _workspace_root
    _workspace_root = path.expanduser().resolve()


def clear_workspace_configuration() -> None:
    """Rimuove il file di configurazione e resetta il workspace in memoria."""
    global _workspace_root
    _workspace_root = None
    try:
        p = workspace_config_path()
        if p.is_file():
            p.unlink()
    except OSError:
        pass


def data_dir() -> Path:
    if _workspace_root is None:
        raise RuntimeError("Cartella dati non configurata (workspace).")
    return _workspace_root


def default_key_file() -> Path:
    return data_dir() / "conti_di_casa.key"


def is_workspace_primary_enc_file(path: Path) -> bool:
    """True se ``path`` è un candidato **database completo** nella cartella dati (directory).

    Esclude il sidecar iOS/desktop ``*_light.enc``, copie ``*_backup.enc`` e nomi tipici delle
    conflicted copy Dropbox. Qualsiasi altro ``*.enc`` nella cartella (anche con nome rinominato
    dall'utente) resta incluso finché passa quei filtri.
    """
    if not path.is_file():
        return False
    name_lower = path.name.lower()
    if not name_lower.endswith(".enc"):
        return False
    if name_lower.endswith("_light.enc"):
        return False
    if name_lower.endswith("_backup.enc"):
        return False
    if "conflicted copy" in name_lower or "copia in conflitto" in name_lower:
        return False
    return True


def primary_user_enc_files_sorted(workspace: Path) -> list[Path]:
    """File ``*.enc`` nella cartella indicata che sono database completi (**non** ``*_light.enc``).

    Ordine: ``st_mtime`` decrescente (più recente per primo). I nomi canonici sono
    ``conti_utente_<hash>.enc``; sono ammessi anche altri stem per cartelle di prova.

    NB: gli ``*.enc`` sotto sole sottocartelle non vengono elencati (solo nella ``workspace`` diretta).
    """
    if not workspace.is_dir():
        return []
    out = [p for p in workspace.glob("*.enc") if is_workspace_primary_enc_file(p)]
    return sorted(out, key=lambda p: p.stat().st_mtime if p.exists() else 0.0, reverse=True)


def legacy_import_dir() -> Path:
    return data_dir() / "legacy_import"


def default_legacy_json_output() -> Path:
    return legacy_import_dir() / "unified_legacy_import.json"


def session_bootstrap_enc_path() -> Path:
    return legacy_import_dir() / "conti_session_bootstrap.enc"


def legacy_project_data_dir() -> Path:
    """Vecchia convenzione: cartella ``data`` accanto all'eseguibile o al cwd."""
    return (app_install_dir() / "data").resolve()


def try_migrate_from_legacy_relative_data() -> Path | None:
    """
    Cerca una cartella dati legacy (``data`` accanto all'exe, Documenti, Dropbox, cwd).
    """
    for d in candidate_legacy_data_dirs():
        if _is_valid_data_dir(d):
            return d
    return None


def _prompt_copy_key_if_missing(parent) -> bool:
    """Se manca la chiave nella cartella dati, chiede di selezionarne una da copiare. Ritorna False se annullato."""
    import tkinter as tk
    from tkinter import filedialog, messagebox

    kf = default_key_file()
    if kf.is_file():
        return True
    if not messagebox.askyesno(
        "Chiave di cifratura",
        "Nella cartella dati non c'è il file conti_di_casa.key.\n\n"
        "Per aprire un database esistente o ripristinare da backup serve quella chiave.\n\n"
        "Vuoi selezionare un file .key da copiare nella cartella dati?",
        parent=_visible_dialog_parent(parent),
    ):
        return False
    picked = filedialog.askopenfilename(
        parent=parent,
        title="Seleziona conti_di_casa.key",
        filetypes=[("Chiave Fernet", "*.key"), ("Tutti i file", "*.*")],
    )
    if not picked:
        return False
    try:
        kf.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(picked, kf)
    except OSError as exc:
        messagebox.showerror("Cartella dati", f"Copia della chiave non riuscita:\n{exc}", parent=parent)
        return False
    return True


def configure_data_workspace_interactive(parent) -> bool:
    """
    Garantisce che ``set_data_workspace_root`` sia impostato, eventualmente dopo dialoghi.
    Ritorna False se l'utente annulla senza configurare.
    """
    import tkinter as tk
    from tkinter import filedialog, messagebox

    import security_auth

    dlg_parent = _visible_dialog_parent(parent)

    saved = load_saved_workspace_path()
    if saved is not None:
        set_data_workspace_root(saved)
        return True

    mig = try_migrate_from_legacy_relative_data()
    if mig is not None:
        save_workspace_path(mig)
        set_data_workspace_root(mig)
        return True

    choice: list[str | None] = [None]

    win = tk.Toplevel(parent)
    win.title("Cartella dati")
    if dlg_parent is not None:
        try:
            win.transient(dlg_parent)
        except Exception:
            pass
    win.resizable(False, False)
    frm = tk.Frame(win, padx=20, pady=16)
    frm.pack(fill=tk.BOTH, expand=True)
    tk.Label(
        frm,
        text=(
            "Scegli dove salvare la chiave e i database (file .enc).\n\n"
            "• Cartella esistente: ad esempio una cartella in Dropbox già sincronizzata.\n"
            "• Backup: ripristino dalla copia in Library richiede la stessa chiave .key\n"
            "  nella cartella che sceglierai (puoi copiarla dopo o selezionarla al passo successivo)."
        ),
        justify=tk.LEFT,
        wraplength=460,
    ).pack(anchor=tk.W)

    btn_row = tk.Frame(frm)
    btn_row.pack(pady=(18, 0))

    _cw_btn = {
        "font": ("TkDefaultFont", 11, "bold"),
        "bg": security_auth.CDC_TIPO_TASTI_BTN_BG,
        "fg": security_auth.CDC_TIPO_TASTI_BTN_FG,
        "activebackground": security_auth.CDC_TIPO_TASTI_BTN_HOVER_BG,
        "activeforeground": security_auth.CDC_TIPO_TASTI_BTN_FG,
        "relief": tk.RAISED,
        "bd": security_auth.CDC_TIPO_TASTI_BTN_BD,
        "highlightthickness": 1,
        "highlightbackground": security_auth.CDC_TIPO_TASTI_BTN_RING,
        "highlightcolor": security_auth.CDC_TIPO_TASTI_BTN_RING,
        "padx": 12,
        "pady": 6,
        "cursor": "hand2",
    }

    def on_pick() -> None:
        choice[0] = "pick"
        win.destroy()

    def on_restore() -> None:
        choice[0] = "restore"
        win.destroy()

    def on_exit() -> None:
        choice[0] = None
        win.destroy()

    tk.Button(btn_row, text="Scegli cartella…", command=on_pick, width=18, **_cw_btn).pack(side=tk.LEFT, padx=(0, 8))
    tk.Button(btn_row, text="Ripristina da backup (Library)…", command=on_restore, width=28, **_cw_btn).pack(
        side=tk.LEFT, padx=(0, 8)
    )
    tk.Button(btn_row, text="Esci", command=on_exit, width=10, **_cw_btn).pack(side=tk.LEFT)

    win.grab_set()
    if dlg_parent is not None:
        try:
            win.update_idletasks()
            px = dlg_parent.winfo_rootx() + (dlg_parent.winfo_width() - win.winfo_reqwidth()) // 2
            py = dlg_parent.winfo_rooty() + (dlg_parent.winfo_height() - win.winfo_reqheight()) // 2
            win.geometry(f"+{max(0, px)}+{max(0, py)}")
        except Exception:
            _center_toplevel_on_screen(win)
    else:
        _center_toplevel_on_screen(win)
    if dlg_parent is not None:
        dlg_parent.wait_window(win)
    else:
        win.wait_window()

    ch = choice[0]
    if ch is None:
        return False

    if ch == "pick":
        folder = filedialog.askdirectory(
            parent=parent,
            title="Scegli la cartella dati (deve già esistere)",
            mustexist=True,
        )
        if not folder:
            return False
        path = Path(folder).expanduser().resolve()
        if not path.is_dir():
            messagebox.showerror("Cartella dati", "Percorso non valido.", parent=dlg_parent)
            return False
        save_workspace_path(path)
        set_data_workspace_root(path)
        return True

    # restore from Library — serve cartella + chiave per decrittare il backup
    folder = filedialog.askdirectory(
        parent=parent,
        title="Scegli la cartella dove verrà ripristinato il database",
        mustexist=True,
    )
    if not folder:
        return False
    path = Path(folder).expanduser().resolve()
    if not path.is_dir():
        messagebox.showerror("Cartella dati", "Percorso non valido.", parent=dlg_parent)
        return False
    save_workspace_path(path)
    set_data_workspace_root(path)
    if not _prompt_copy_key_if_missing(parent):
        messagebox.showwarning(
            "Cartella dati",
            "Senza conti_di_casa.key nella cartella non è possibile ripristinare.\n"
            "Copia la chiave e riavvia l'applicazione.",
            parent=dlg_parent,
        )
        clear_workspace_configuration()
        return False
    return True
