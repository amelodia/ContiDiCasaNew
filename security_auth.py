"""
Accesso al programma: primo avvio, login, backdoor, stato registrato / non registrato,
notifica email e conferma registrazione via IMAP.
"""
from __future__ import annotations

import hashlib
import re
import secrets
import time
import tkinter as tk
from dataclasses import dataclass
from tkinter import messagebox, ttk
from typing import Any, Callable

SaveFn = Callable[[], None]

DEFAULT_USER_PROFILE: dict[str, Any] = {
    "display_name_suffix": "",
    "email": "",
    "password_hash": "",
    "salt": "",
    "registration_verified": False,
}

DEFAULT_SECURITY_CONFIG: dict[str, Any] = {
    "admin_notify_email": "",
}


def ensure_security(db: dict) -> None:
    if "user_profile" not in db or not isinstance(db["user_profile"], dict):
        db["user_profile"] = dict(DEFAULT_USER_PROFILE)
    else:
        for k, v in DEFAULT_USER_PROFILE.items():
            if k not in db["user_profile"]:
                db["user_profile"][k] = v
    if "security_config" not in db or not isinstance(db["security_config"], dict):
        db["security_config"] = dict(DEFAULT_SECURITY_CONFIG)
    else:
        for k, v in DEFAULT_SECURITY_CONFIG.items():
            if k not in db["security_config"]:
                db["security_config"][k] = v


def needs_first_access_setup(db: dict) -> bool:
    ensure_security(db)
    up = db["user_profile"]
    if (up.get("password_hash") or "").strip():
        return False
    return True


def _hash_password(password: str, salt_hex: str) -> str:
    salt = bytes.fromhex(salt_hex)
    dk = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, 120_000)
    return dk.hex()


def set_password(up: dict, plain: str) -> None:
    salt = secrets.token_bytes(16)
    up["salt"] = salt.hex()
    up["password_hash"] = _hash_password(plain, up["salt"])


def verify_password(up: dict, plain: str) -> bool:
    h = (up.get("password_hash") or "").strip()
    s = (up.get("salt") or "").strip()
    if not h or not s:
        return False
    try:
        return secrets.compare_digest(_hash_password(plain, s), h)
    except Exception:
        return False


@dataclass
class AppSession:
    """Stato sessione dopo il login."""

    is_registered: bool
    entered_via_backdoor: bool
    entered_via_guest: bool
    user_email: str | None


def run_first_access_wizard_if_needed(
    parent: tk.Tk,
    db: dict,
    save: SaveFn,
) -> bool:
    """Ritorna False se l'utente annulla o non completa."""
    if not needs_first_access_setup(db):
        return True

    win = tk.Toplevel(parent)
    win.title("Primo accesso — Conti di casa")
    win.transient(parent)
    win.resizable(True, False)
    win.grab_set()
    frm = ttk.Frame(win, padding=16)
    frm.pack(fill=tk.BOTH, expand=True)

    ttk.Label(frm, text='Come vuoi chiamare Conti di casa? (completa la frase)', font=("TkDefaultFont", 12)).pack(anchor=tk.W)
    row1 = ttk.Frame(frm)
    row1.pack(fill=tk.X, pady=(8, 4))
    ttk.Label(row1, text="Conti di casa", font=("TkDefaultFont", 13, "bold")).pack(side=tk.LEFT)
    suffix_var = tk.StringVar()
    ttk.Entry(row1, textvariable=suffix_var, width=40).pack(side=tk.LEFT, padx=(6, 0))

    ttk.Label(frm, text="Email (nome utente per gli accessi successivi)", font=("TkDefaultFont", 12)).pack(anchor=tk.W, pady=(14, 0))
    email_var = tk.StringVar()
    ttk.Entry(frm, textvariable=email_var, width=52).pack(anchor=tk.W, pady=(4, 0))

    ttk.Label(frm, text="Password (almeno 5 caratteri)", font=("TkDefaultFont", 12)).pack(anchor=tk.W, pady=(10, 0))
    pw1_var = tk.StringVar()
    pw2_var = tk.StringVar()
    ttk.Entry(frm, textvariable=pw1_var, width=32, show="•").pack(anchor=tk.W, pady=(4, 2))
    ttk.Label(frm, text="Ripeti password", font=("TkDefaultFont", 11)).pack(anchor=tk.W)
    ttk.Entry(frm, textvariable=pw2_var, width=32, show="•").pack(anchor=tk.W, pady=(4, 0))

    err = tk.StringVar()
    ttk.Label(frm, textvariable=err, foreground="red", wraplength=480).pack(anchor=tk.W, pady=(8, 0))

    result: list[bool | None] = [None]

    def finish() -> None:
        suf = (suffix_var.get() or "").strip()
        em = (email_var.get() or "").strip()
        p1 = pw1_var.get() or ""
        p2 = pw2_var.get() or ""
        if len(suf) < 1:
            err.set("Inserisci come vuoi completare il nome «Conti di casa …».")
            return
        if "@" not in em or "." not in em.split("@")[-1]:
            err.set("Inserisci un indirizzo email valido.")
            return
        if len(p1) < 5:
            err.set("La password deve avere almeno 5 caratteri.")
            return
        if p1 != p2:
            err.set("Le due password non coincidono.")
            return
        ensure_security(db)
        up = db["user_profile"]
        up["display_name_suffix"] = suf
        up["email"] = em.lower()
        up["registration_verified"] = False
        set_password(up, p1)
        try:
            save()
        except Exception as exc:
            messagebox.showerror("Primo accesso", f"Salvataggio non riuscito:\n{exc}")
            return

        try:
            import email_client

            email_client.send_registration_signup_notification(db, display_suffix=suf, user_email=em.lower())
        except Exception:
            pass

        messagebox.showinfo(
            "Primo accesso",
            "Dati memorizzati.\n\n"
            "Puoi entrare nel programma come utente non registrato dal login (tasto dedicato), "
            "oppure con email e password quando vorrai.\n"
            "Riceverai o potrai ricevere comunicazioni successive sulla registrazione.\n\n"
            "Se l'email di notifica è configurata, è stata inviata una segnalazione all'amministratore.",
        )
        result[0] = True
        win.destroy()

    def on_cancel() -> None:
        if messagebox.askyesno("Uscita", "Uscire senza completare il primo accesso?"):
            result[0] = False
            win.destroy()

    rowb = ttk.Frame(frm)
    rowb.pack(pady=(16, 0))
    ttk.Button(rowb, text="Continua", command=finish).pack(side=tk.LEFT, padx=(0, 8))
    ttk.Button(rowb, text="Annulla", command=on_cancel).pack(side=tk.LEFT)

    win.protocol("WM_DELETE_WINDOW", on_cancel)
    try:
        win.update_idletasks()
        w = win.winfo_reqwidth()
        h = win.winfo_reqheight()
        sw = win.winfo_screenwidth()
        sh = win.winfo_screenheight()
        win.geometry(f"+{(sw - w) // 2}+{(sh - h) // 3}")
    except Exception:
        pass

    parent.wait_window(win)
    return result[0] is True


def run_login_dialog(parent: tk.Tk, db: dict, save: SaveFn) -> tuple[bool, AppSession | None]:
    """Finestra login. Ritorna (True, session) o (False, None)."""
    ensure_security(db)
    up = db["user_profile"]
    has_password = bool((up.get("password_hash") or "").strip())

    win = tk.Toplevel(parent)
    win.title("Accesso — Conti di casa")
    win.transient(parent)
    win.resizable(False, False)
    win.grab_set()

    frm = ttk.Frame(win, padding=18)
    frm.pack(fill=tk.BOTH, expand=True)

    ttk.Label(frm, text="Email", font=("TkDefaultFont", 12)).grid(row=0, column=0, sticky="w")
    email_var = tk.StringVar(value=(up.get("email") or ""))
    ttk.Entry(frm, textvariable=email_var, width=42).grid(row=1, column=0, columnspan=2, sticky="we", pady=(2, 8))

    ttk.Label(frm, text="Password", font=("TkDefaultFont", 12)).grid(row=2, column=0, sticky="w")
    pw_var = tk.StringVar()
    ent_pw = ttk.Entry(frm, textvariable=pw_var, width=42, show="•")
    ent_pw.grid(row=3, column=0, columnspan=2, sticky="we", pady=(2, 10))

    hint = ttk.Label(
        frm,
        text="Accesso tecnico: premi Ctrl+Z e subito dopo Ctrl+X (entro circa un secondo).",
        font=("TkDefaultFont", 9),
        foreground="#666",
        wraplength=420,
    )
    hint.grid(row=4, column=0, columnspan=2, sticky="w", pady=(0, 10))

    out: list[tuple[bool, AppSession | None]] = [(False, None)]

    backdoor = _BackdoorState()

    def do_login() -> None:
        if not has_password:
            messagebox.showerror("Accesso", "Profilo non inizializzato.")
            return
        em = (email_var.get() or "").strip().lower()
        pw = pw_var.get() or ""
        if not em or not pw:
            messagebox.showerror("Accesso", "Inserisci email e password.")
            return
        if em != (up.get("email") or "").strip().lower():
            messagebox.showerror("Accesso", "Email non riconosciuta.")
            return
        if not verify_password(up, pw):
            messagebox.showerror("Accesso", "Password non corretta.")
            return
        verified = bool(up.get("registration_verified"))
        sess = AppSession(
            is_registered=verified,
            entered_via_backdoor=False,
            entered_via_guest=False,
            user_email=em,
        )
        out[0] = (True, sess)
        win.destroy()

    def do_guest() -> None:
        sess = AppSession(
            is_registered=False,
            entered_via_backdoor=False,
            entered_via_guest=True,
            user_email=None,
        )
        out[0] = (True, sess)
        win.destroy()

    def do_backdoor() -> None:
        sess = AppSession(
            is_registered=True,
            entered_via_backdoor=True,
            entered_via_guest=False,
            user_email=(up.get("email") or None),
        )
        out[0] = (True, sess)
        win.destroy()

    def on_ctrl_z(_e: tk.Event) -> str | None:
        backdoor.mark_z()
        return "break"

    def on_ctrl_x(_e: tk.Event) -> str | None:
        if backdoor.consume_for_backdoor():
            do_backdoor()
        return "break"

    rowb = ttk.Frame(frm)
    rowb.grid(row=5, column=0, columnspan=2, sticky="we", pady=(4, 0))
    ttk.Button(rowb, text="Accedi", command=do_login).pack(side=tk.LEFT, padx=(0, 8))
    ttk.Button(rowb, text="Accesso non registrato", command=do_guest).pack(side=tk.LEFT, padx=(0, 8))
    ttk.Button(rowb, text="Esci", command=lambda: win.destroy()).pack(side=tk.LEFT)

    win.bind("<Control-z>", on_ctrl_z)
    win.bind("<Control-Z>", on_ctrl_z)
    win.bind("<Control-x>", on_ctrl_x)
    win.bind("<Control-X>", on_ctrl_x)
    ent_pw.bind("<Control-z>", on_ctrl_z)
    ent_pw.bind("<Control-Z>", on_ctrl_z)
    ent_pw.bind("<Control-x>", on_ctrl_x)
    ent_pw.bind("<Control-X>", on_ctrl_x)

    def on_close() -> None:
        win.destroy()

    win.protocol("WM_DELETE_WINDOW", on_close)

    try:
        win.update_idletasks()
        w = 460
        h = win.winfo_reqheight() + 40
        sw = win.winfo_screenwidth()
        sh = win.winfo_screenheight()
        win.geometry(f"{w}x{h}+{(sw - w) // 2}+{(sh - h) // 3}")
    except Exception:
        pass

    parent.wait_window(win)
    ok, sess = out[0]
    return ok, sess


class _BackdoorState:
    def __init__(self) -> None:
        self._z_at: float = 0.0

    def mark_z(self) -> None:
        self._z_at = time.monotonic()

    def consume_for_backdoor(self) -> bool:
        if self._z_at <= 0:
            return False
        if time.monotonic() - self._z_at <= 1.25:
            self._z_at = 0.0
            return True
        self._z_at = 0.0
        return False


def poll_registration_emails(db: dict) -> bool:
    """
    Controlla la posta IMAP per messaggi che contengono REGISTRA:<email>.
    Se corrisponde all'email utente, imposta registration_verified.
    Ritorna True se il database va salvato.
    """
    import email_client

    ensure_security(db)
    up = db["user_profile"]
    em = (up.get("email") or "").strip().lower()
    if not em or up.get("registration_verified"):
        return False
    try:
        if email_client.scan_inbox_for_registration_approval(db, target_email=em):
            up["registration_verified"] = True
            return True
    except Exception:
        pass
    return False
