"""
Accesso al programma: primo avvio, login, backdoor, stato registrato / non registrato,
notifica email e conferma registrazione via IMAP.
"""
from __future__ import annotations

import base64
import hashlib
import io
import platform
import re
import secrets
import sys
import time
import tkinter as tk
from dataclasses import dataclass
from pathlib import Path
from tkinter import messagebox, ttk
from typing import Any, Callable

SaveFn = Callable[[], None]

# Versione mostrata nella finestra di accesso (allineare al rilascio).
APP_VERSION = "1.0.0"

# Colori finestra di accesso.
_LOGIN_IMG_CANVAS_BG = "#d8ecf5"
_LOGIN_BTN_FG = "#000000"
_LOGIN_BTN_ACTIVE_BG = "#c9e4ef"  # azzurro leggermente più scuro al click

# Area immagine euro (compatta).
_LOGIN_BANNER_AREA_HEIGHT = 128
_LOGIN_BANNER_AREA_WIDTH = 300
_LOGIN_EURO_DISPLAY_MAX = 118

# Finestra login: larghezza minima modesta; altezza segue il contenuto (niente “vuoto” sotto i tasti).
_LOGIN_WIN_MIN_W = 400
_LOGIN_WIN_MIN_H = 1
# ~0,5 cm di margine in più sotto il contenuto (padding inferiore del riquadro principale).
_LOGIN_OUTER_PAD_BOTTOM_PX = 22


def _security_auth_package_dir() -> Path:
    """Directory del modulo (o estratto PyInstaller)."""
    if getattr(sys, "frozen", False):
        meipass = getattr(sys, "_MEIPASS", None)
        if meipass:
            return Path(meipass)
    return Path(__file__).resolve().parent


def _login_bg_rgb() -> tuple[int, int, int]:
    s = _LOGIN_IMG_CANVAS_BG.strip().lstrip("#")
    if len(s) != 6:
        return 216, 236, 245
    return int(s[0:2], 16), int(s[2:4], 16), int(s[4:6], 16)


def _login_euro_jpeg_bytes() -> bytes | None:
    """Solo JPEG incorporato in ``euro_login_asset`` (niente file esterni: evita vecchie monete da assets/)."""
    try:
        from euro_login_asset import EURO_JPEG_B64

        return base64.b64decode(EURO_JPEG_B64)
    except Exception:
        return None


def verify_pillow_for_login_ui(parent: tk.Misc | None = None) -> bool:
    """
    Pillow è obbligatorio per mostrare l'immagine nella finestra di accesso (ImageTk + JPEG incorporato).
    Restituisce False e mostra un messaggio se manca (utile anche per verifiche pre-compilazione manuale).
    """
    try:
        from PIL import Image, ImageTk  # noqa: F401

        return True
    except ImportError:
        messagebox.showerror(
            "Dipendenza mancante — Pillow",
            "L'applicazione richiede Pillow per la finestra di accesso (immagine JPEG incorporata).\n\n"
            "Installazione:\n  python3 -m pip install Pillow\n\n"
            "Compilazione (PyInstaller/equivalenti): includere il pacchetto Pillow "
            "(verificare che risultino inclusi PIL, PIL.Image, PIL.ImageTk).",
            parent=parent,
        )
        return False


def _pil_lanczos(Image: Any) -> Any:
    return Image.Resampling.LANCZOS if hasattr(Image, "Resampling") else Image.LANCZOS


def _load_login_euro_from_jpeg_bytes(data: bytes, *, max_side: int) -> tk.PhotoImage | None:
    """Apre JPEG/PNG da buffer con Pillow, ridimensiona, restituisce ``ImageTk.PhotoImage``."""
    try:
        from PIL import Image, ImageTk

        im = Image.open(io.BytesIO(data))
        im.load()
        if im.mode == "P":
            im = im.convert("RGBA")
        elif im.mode not in ("RGB", "RGBA"):
            im = im.convert("RGB")
        if im.mode == "RGBA":
            im.thumbnail((max_side, max_side), _pil_lanczos(Image))
            base = Image.new("RGB", im.size, _login_bg_rgb())
            base.paste(im, mask=im.split()[3])
            return ImageTk.PhotoImage(base)
        im.thumbnail((max_side, max_side), _pil_lanczos(Image))
        return ImageTk.PhotoImage(im)
    except Exception:
        return None


def _load_login_euro_photo(*, max_side: int) -> tk.PhotoImage | None:
    raw = _login_euro_jpeg_bytes()
    if not raw:
        return None
    return _load_login_euro_from_jpeg_bytes(raw, max_side=max_side)


def _present_modal_dialog(win: tk.Toplevel, parent: tk.Tk) -> None:
    """Porta in primo piano la finestra modale (utile su macOS)."""
    try:
        parent.update_idletasks()
        win.update_idletasks()
        try:
            parent_visible = bool(int(str(parent.winfo_viewable())))
        except (tk.TclError, TypeError, ValueError):
            parent_visible = False
        if parent_visible:
            win.lift(parent)
        else:
            win.lift()
        win.focus_force()
        if platform.system() == "Darwin":
            try:
                win.attributes("-topmost", True)
                win.after(100, lambda: win.attributes("-topmost", False))
            except Exception:
                pass
    except Exception:
        pass


DEFAULT_USER_PROFILE: dict[str, Any] = {
    "display_name_suffix": "",
    "email": "",
    "password_hash": "",
    "salt": "",
    "registration_verified": False,
}

DEFAULT_SECURITY_CONFIG: dict[str, Any] = {
    "admin_notify_email": "",
    # True dopo test SMTP+IMAP riuscito in Opzioni (UI compatta).
    "email_verified_ok": False,
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


def reset_user_profile_for_registration_restart(db: dict) -> None:
    """Azzera il profilo locale così da poter ripetere il primo accesso (nuova registrazione / notifiche)."""
    ensure_security(db)
    db["user_profile"] = dict(DEFAULT_USER_PROFILE)


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
        except Exception as exc:
            messagebox.showwarning(
                "Primo accesso — email",
                "Dati salvati, ma l'invio delle email non è riuscito.\n\n"
                f"Dettaglio tecnico:\n{exc}\n\n"
                "Controlla in Opzioni → Posta e sicurezza: SMTP, password (con Gmail serve la "
                "«password per le app»), e avvia «Test connessione». "
                "Una volta sistemato, puoi ripetere il primo accesso per reinviare le email.",
            )
        else:
            messagebox.showinfo(
                "Primo accesso",
                "Dati memorizzati.\n\n"
                "Dovresti ricevere una email di conferma su " + em.lower() + " (controlla anche lo spam).\n\n"
                "Se è impostata l'email amministratore, riceve anche la notifica con REGISTRA:… o REGISTRATO:…\n\n"
                "Puoi entrare come utente non registrato dal login, oppure con email e password.",
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

    _present_modal_dialog(win, parent)
    parent.wait_window(win)
    return result[0] is True


def run_login_dialog(parent: tk.Tk, db: dict, save: SaveFn) -> tuple[bool, AppSession | None]:
    """Finestra login. Ritorna (True, session) o (False, None)."""
    ensure_security(db)
    up = db["user_profile"]
    has_password = bool((up.get("password_hash") or "").strip())

    win = tk.Toplevel(parent)
    win.title(f"Accesso — Conti di casa {APP_VERSION}")
    try:
        win.configure(bg=_LOGIN_IMG_CANVAS_BG)
    except Exception:
        pass
    win.resizable(False, False)
    win.grab_set()

    _login_style = ttk.Style()
    try:
        _login_style.configure("CdcLogin.TLabel", background=_LOGIN_IMG_CANVAS_BG, foreground="#1a1a1a")
    except Exception:
        pass

    outer = tk.Frame(win, bg=_LOGIN_IMG_CANVAS_BG)
    outer.pack(padx=14, pady=(8, _LOGIN_OUTER_PAD_BOTTOM_PX))
    outer.columnconfigure(0, weight=1)

    banner_wrap = tk.Frame(outer, bg=_LOGIN_IMG_CANVAS_BG)
    banner_wrap.grid(row=0, column=0, sticky="ew", pady=(0, 8))
    banner_wrap.columnconfigure(0, weight=1)

    banner_inner = tk.Frame(
        banner_wrap,
        bg=_LOGIN_IMG_CANVAS_BG,
        width=_LOGIN_BANNER_AREA_WIDTH,
        height=_LOGIN_BANNER_AREA_HEIGHT,
        highlightthickness=0,
    )
    banner_inner.grid(row=0, column=0, sticky="")
    banner_inner.grid_propagate(False)

    win._login_banner_photo = _load_login_euro_photo(max_side=_LOGIN_EURO_DISPLAY_MAX)

    euro_lbl = tk.Label(
        banner_inner,
        bg=_LOGIN_IMG_CANVAS_BG,
        bd=0,
        highlightthickness=0,
    )
    if win._login_banner_photo is not None:
        euro_lbl.config(image=win._login_banner_photo)
        euro_lbl.image = win._login_banner_photo
    euro_lbl.place(relx=0.5, rely=0.5, anchor="center")

    frm = tk.Frame(outer, bg=_LOGIN_IMG_CANVAS_BG)
    frm.grid(row=1, column=0, sticky="ew")
    frm.columnconfigure(0, weight=1)

    email_row = 0
    if win._login_banner_photo is None:
        euro_lbl.config(
            text="Immagine accesso non disponibile (dati incorporati non leggibili).",
            fg="#555555",
            font=("TkDefaultFont", 10),
            wraplength=_LOGIN_BANNER_AREA_WIDTH - 24,
            justify="center",
        )

    ttk.Label(frm, text="Email", font=("TkDefaultFont", 12), style="CdcLogin.TLabel").grid(
        row=email_row, column=0, sticky="w"
    )
    email_var = tk.StringVar(value=(up.get("email") or ""))
    ent_email = ttk.Entry(frm, textvariable=email_var, width=38)
    ent_email.grid(row=email_row + 1, column=0, columnspan=2, sticky="we", pady=(2, 8))

    ttk.Label(frm, text="Password", font=("TkDefaultFont", 12), style="CdcLogin.TLabel").grid(
        row=email_row + 2, column=0, sticky="w"
    )
    pw_var = tk.StringVar()
    ent_pw = ttk.Entry(frm, textvariable=pw_var, width=38, show="•")
    ent_pw.grid(row=email_row + 3, column=0, columnspan=2, sticky="we", pady=(2, 6))

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

    rowb = tk.Frame(frm, bg=_LOGIN_IMG_CANVAS_BG)
    rowb.grid(row=email_row + 4, column=0, columnspan=2, sticky="we", pady=(2, 0))
    _btn_kw: dict[str, Any] = {
        "bg": _LOGIN_IMG_CANVAS_BG,
        "fg": _LOGIN_BTN_FG,
        "font": ("TkDefaultFont", 11, "bold"),
        "activebackground": _LOGIN_BTN_ACTIVE_BG,
        "activeforeground": _LOGIN_BTN_FG,
        "relief": tk.RAISED,
        "borderwidth": 1,
        "highlightbackground": _LOGIN_IMG_CANVAS_BG,
        "highlightcolor": _LOGIN_IMG_CANVAS_BG,
        "padx": 8,
        "pady": 4,
        "highlightthickness": 0,
        "cursor": "hand2",
    }
    tk.Button(rowb, text="Accedi", command=do_login, **_btn_kw).pack(side=tk.LEFT, padx=(0, 8))
    tk.Button(rowb, text="Accesso non registrato", command=do_guest, **_btn_kw).pack(side=tk.LEFT, padx=(0, 8))
    tk.Button(rowb, text="Esci", command=lambda: win.destroy(), **_btn_kw).pack(side=tk.LEFT)

    win.bind("<Control-z>", on_ctrl_z)
    win.bind("<Control-Z>", on_ctrl_z)
    win.bind("<Control-x>", on_ctrl_x)
    win.bind("<Control-X>", on_ctrl_x)
    ent_pw.bind("<Control-z>", on_ctrl_z)
    ent_pw.bind("<Control-Z>", on_ctrl_z)
    ent_pw.bind("<Control-x>", on_ctrl_x)
    ent_pw.bind("<Control-X>", on_ctrl_x)
    ent_email.bind("<Control-z>", on_ctrl_z)
    ent_email.bind("<Control-Z>", on_ctrl_z)
    ent_email.bind("<Control-x>", on_ctrl_x)
    ent_email.bind("<Control-X>", on_ctrl_x)

    def on_return_login(_e: tk.Event | None = None) -> str:
        do_login()
        return "break"

    ent_email.bind("<Return>", on_return_login)
    ent_email.bind("<KP_Enter>", on_return_login)
    ent_pw.bind("<Return>", on_return_login)
    ent_pw.bind("<KP_Enter>", on_return_login)

    def on_close() -> None:
        win.destroy()

    win.protocol("WM_DELETE_WINDOW", on_close)

    try:
        win.update_idletasks()
        sw = win.winfo_screenwidth()
        sh = win.winfo_screenheight()
        rw = max(win.winfo_reqwidth(), _LOGIN_WIN_MIN_W)
        rh = max(win.winfo_reqheight(), _LOGIN_WIN_MIN_H)
        w = min(rw, int(sw * 0.92))
        h = min(rh, int(sh * 0.88))
        win.geometry(f"{w}x{h}+{(sw - w) // 2}+{(sh - h) // 3}")
        win.minsize(w, h)
    except Exception:
        pass

    _present_modal_dialog(win, parent)
    try:
        ent_pw.focus_set()
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
    Controlla la posta IMAP per messaggi che contengono REGISTRA:<email> o REGISTRATO:<email>.
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
