"""
Cartella dati configurabile dall'utente: contiene ``conti_di_casa.key``, i file ``.enc``,
la sottocartella ``legacy_import/`` (JSON unificato e bootstrap sessione).

Il percorso scelto è salvato in ``~/Library/Application Support/ContiDiCasa/data_workspace.json``.
"""
from __future__ import annotations

import json
import shutil
from pathlib import Path

_CONFIG_NAME = "data_workspace.json"

_workspace_root: Path | None = None


def app_support_dir() -> Path:
    return Path.home() / "Library" / "Application Support" / "ContiDiCasa"


def workspace_config_path() -> Path:
    return app_support_dir() / _CONFIG_NAME


def _read_workspace_config() -> dict:
    p = workspace_config_path()
    if not p.is_file():
        return {}
    try:
        obj = json.loads(p.read_text(encoding="utf-8"))
        return obj if isinstance(obj, dict) else {}
    except Exception:
        return {}


def _write_workspace_config(obj: dict) -> None:
    app_support_dir().mkdir(parents=True, exist_ok=True)
    workspace_config_path().write_text(
        json.dumps(obj, ensure_ascii=True, indent=2) + "\n",
        encoding="utf-8",
    )


def load_saved_workspace_path() -> Path | None:
    """Restituisce il percorso assoluto se il file di configurazione indica una directory esistente."""
    try:
        obj = _read_workspace_config()
        raw = obj.get("workspace_path") or obj.get("path")
        if not raw:
            return None
        path = Path(str(raw)).expanduser().resolve()
        if path.is_dir():
            return path
    except Exception:
        pass
    return None


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


def primary_user_enc_files_sorted(workspace: Path) -> list[Path]:
    """File ``conti_utente_<hash>.enc`` nella cartella dati, **senza** il sidecar ``*_light.enc`` dell'app iOS.

    Ordine: ``st_mtime`` decrescente (il più recentemente modificato per primo). Il pattern ``conti_utente_*.enc``
    altrimenti includerebbe anche ``…_light.enc``, spesso più recente del file completo e scelto per errore.
    """
    out: list[Path] = []
    for p in workspace.glob("conti_utente_*.enc"):
        if not p.is_file():
            continue
        if p.name.endswith("_light.enc"):
            continue
        out.append(p)
    return sorted(out, key=lambda p: p.stat().st_mtime, reverse=True)


def legacy_import_dir() -> Path:
    return data_dir() / "legacy_import"


def default_legacy_json_output() -> Path:
    return legacy_import_dir() / "unified_legacy_import.json"


def session_bootstrap_enc_path() -> Path:
    return legacy_import_dir() / "conti_session_bootstrap.enc"


def legacy_project_data_dir() -> Path:
    """Vecchia convenzione: cartella ``data`` sotto la directory di lavoro corrente."""
    return (Path.cwd() / "data").resolve()


def try_migrate_from_legacy_relative_data() -> Path | None:
    """
    Se esiste ``./data`` (cwd) con almeno un file ``conti_utente_*.enc`` o ``conti_di_casa.key``,
    restituisce quel percorso per proporre la migrazione.
    """
    d = legacy_project_data_dir()
    if not d.is_dir():
        return None
    if (d / "conti_di_casa.key").is_file():
        return d
    if list(d.glob("conti_utente_*.enc")):
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
        parent=parent,
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

    saved = load_saved_workspace_path()
    if saved is not None:
        set_data_workspace_root(saved)
        return True

    mig = try_migrate_from_legacy_relative_data()
    if mig is not None:
        if messagebox.askyesno(
            "Cartella dati",
            f"È stata trovata una cartella dati locale del progetto:\n{mig}\n\n"
            "Vuoi usarla come cartella dati dell'applicazione?\n\n"
            "(Consigliato se prima usavi la cartella «data» accanto al progetto.)",
            parent=parent,
        ):
            save_workspace_path(mig)
            set_data_workspace_root(mig)
            return True

    choice: list[str | None] = [None]

    win = tk.Toplevel(parent)
    win.title("Cartella dati")
    win.transient(parent)
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

    def on_pick() -> None:
        choice[0] = "pick"
        win.destroy()

    def on_restore() -> None:
        choice[0] = "restore"
        win.destroy()

    def on_exit() -> None:
        choice[0] = None
        win.destroy()

    tk.Button(btn_row, text="Scegli cartella…", command=on_pick, width=18).pack(side=tk.LEFT, padx=(0, 8))
    tk.Button(btn_row, text="Ripristina da backup (Library)…", command=on_restore, width=28).pack(
        side=tk.LEFT, padx=(0, 8)
    )
    tk.Button(btn_row, text="Esci", command=on_exit, width=10).pack(side=tk.LEFT)

    win.grab_set()
    try:
        win.update_idletasks()
        px = parent.winfo_rootx() + (parent.winfo_width() - win.winfo_reqwidth()) // 2
        py = parent.winfo_rooty() + (parent.winfo_height() - win.winfo_reqheight()) // 2
        win.geometry(f"+{max(0, px)}+{max(0, py)}")
    except Exception:
        pass
    parent.wait_window(win)

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
            messagebox.showerror("Cartella dati", "Percorso non valido.", parent=parent)
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
        messagebox.showerror("Cartella dati", "Percorso non valido.", parent=parent)
        return False
    save_workspace_path(path)
    set_data_workspace_root(path)
    if not _prompt_copy_key_if_missing(parent):
        messagebox.showwarning(
            "Cartella dati",
            "Senza conti_di_casa.key nella cartella non è possibile ripristinare.\n"
            "Copia la chiave e riavvia l'applicazione.",
            parent=parent,
        )
        clear_workspace_configuration()
        return False
    return True
