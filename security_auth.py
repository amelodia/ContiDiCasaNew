"""
Accesso al programma: primo avvio, login, backdoor, stato registrato / non registrato,
notifica email e conferma registrazione via IMAP, percorso «Nuova utenza» (wizard senza perdere posta/sicurezza).
"""
from __future__ import annotations

import base64
import hashlib
import io
import os
import platform
import re
import secrets
import sys
import time
from datetime import datetime, timezone
import tkinter as tk
from dataclasses import dataclass
from pathlib import Path
from tkinter import messagebox, ttk
from typing import Any, Callable

from app_version import APP_VERSION

SaveFn = Callable[[], None]

# Sfondo azzurro chiaro (pagine principali dopo l’accesso, stesso tono in ``main_app.MOVIMENTI_PAGE_BG``).
CDC_AZZURRO_CHIARO_BG = "#d8ecf5"
# Finestra di accesso: pesca molto chiaro, coerente con ``CDC_TIPO_TASTI_BTN_*``.
CDC_LOGIN_WIN_BG = "#fff5f0"
# Compositing immagine euro + riempimenti ``tk`` nella finestra login.
_LOGIN_IMG_CANVAS_BG = CDC_LOGIN_WIN_BG

# Palette «tipo tasti»: non selezionato = giallo-arancio chiaro (tocco di rosso); selezionato = arancio più scuro; hover = intermedio.
CDC_TIPO_TASTI_BTN_BG = "#ffe4c4"
CDC_TIPO_TASTI_BTN_HOVER_BG = "#ffb078"
CDC_TIPO_TASTI_BTN_ACTIVE_BG = "#c45a18"
CDC_TIPO_TASTI_BTN_FG = "#3d1a0a"
CDC_TIPO_TASTI_BTN_RING = "#e88840"
CDC_TIPO_TASTI_BTN_RING_FOCUS = "#9a4810"
# Campi testo login: più chiaro dei tasti «spenti», stessa famiglia cromatica.
CDC_TIPO_TASTI_FIELD_BG = "#fff4ea"
# Cornice (``tk.Label`` / ``tk.Button`` in rilievo): login, barra schede pagine; chip filtro in ``main_app``.
CDC_TIPO_TASTI_BTN_BD = 3

# Fallback per altri ``_login_action_label`` senza colori dedicati.
_LOGIN_BTN_FG = CDC_TIPO_TASTI_BTN_FG
_LOGIN_BTN_BG = CDC_TIPO_TASTI_BTN_BG
_LOGIN_BTN_ACTIVE_BG = CDC_TIPO_TASTI_BTN_HOVER_BG
# Larghezza in caratteri allineata ad «Accedi» per tasti corti (es. «Esci»).
_LOGIN_BTN_WIDTH_ACCEDI_CHARS = len("Accedi")

# Area immagine euro (compatta).
_LOGIN_BANNER_AREA_HEIGHT = 128
_LOGIN_BANNER_AREA_WIDTH = 300
_LOGIN_EURO_DISPLAY_MAX = 118

# Finestra login: larghezza minima modesta; altezza segue il contenuto (niente “vuoto” sotto i tasti).
_LOGIN_WIN_MIN_W = 400
_LOGIN_WIN_MIN_H = 1
# Primo accesso (wizard): dimensioni minime esplicite — su macOS senza ``WxH`` la finestra può risultare troppo bassa e nascondere «Continua» / «Annulla».
_FIRST_ACCESS_WIN_MIN_W = 480
_FIRST_ACCESS_WIN_MIN_H = 360
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
        return 255, 245, 240
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
    # Istante UTC (ISO) dopo cui la scan IMAP accetta REGISTRA:/REGISTRATO: (evita match su mail vecchie).
    "registration_poll_not_before_iso": "",
    # True dopo «Nuova utenza» + DB contabile vuoto: aprire scheda Categorie e conti quando la posta è configurata.
    "plan_conti_wizard_pending": False,
}

DEFAULT_SECURITY_CONFIG: dict[str, Any] = {
    "admin_notify_email": "",
    # True dopo test SMTP+IMAP riuscito in Opzioni (UI compatta).
    "email_verified_ok": False,
}


def _login_prefill_email(up: dict) -> str:
    """Email nel campo accesso: ultima usata (persistente), poi profilo DB, poi env."""
    try:
        import data_workspace

        le = data_workspace.load_last_login_email()
        if le:
            return le
    except Exception:
        pass
    prof = (up.get("email") or "").strip()
    if prof:
        return prof
    for key in ("CONTI_LOGIN_EMAIL", "CONTI_DEFAULT_LOGIN_EMAIL", "CONTI_LOGIN_USERID"):
        v = (os.environ.get(key) or "").strip()
        if v:
            return v
    return ""


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


def prepare_database_for_nuova_utenza(db: dict) -> None:
    """Nuova utenza: profilo e opzioni applicative ripartono da zero (l’utenza precedente va sul suo file .enc)."""
    import email_client
    import periodiche

    ensure_security(db)
    db["user_profile"] = dict(DEFAULT_USER_PROFILE)
    db["email_settings"] = dict(email_client.DEFAULT_EMAIL_SETTINGS)
    db["security_config"] = dict(DEFAULT_SECURITY_CONFIG)
    db["periodic_registrations"] = []
    ensure_security(db)
    email_client.ensure_email_settings(db)
    periodiche.ensure_periodic_registrations(db)


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
    try:
        win.transient(parent)
    except Exception:
        pass
    try:
        win.withdraw()
    except Exception:
        pass
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
        up["registration_poll_not_before_iso"] = datetime.now(timezone.utc).isoformat()
        try:
            save()
        except Exception as exc:
            messagebox.showerror(
                "Primo accesso",
                "Salvataggio della soglia per la verifica email non riuscito:\n"
                f"{exc}\n\n"
                "Ripeti il primo accesso o controlla il file del database.",
            )
            return
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
        sw = win.winfo_screenwidth()
        sh = win.winfo_screenheight()
        rw = max(win.winfo_reqwidth(), _FIRST_ACCESS_WIN_MIN_W)
        rh = max(win.winfo_reqheight(), _FIRST_ACCESS_WIN_MIN_H)
        ww = min(rw, int(sw * 0.92))
        wh = min(rh, int(sh * 0.88))
        win.geometry(f"{ww}x{wh}+{(sw - ww) // 2}+{(sh - wh) // 3}")
        win.minsize(_FIRST_ACCESS_WIN_MIN_W, _FIRST_ACCESS_WIN_MIN_H)
    except Exception:
        try:
            win.geometry(
                f"{_FIRST_ACCESS_WIN_MIN_W}x{_FIRST_ACCESS_WIN_MIN_H}+100+100"
            )
        except Exception:
            pass

    try:
        win.deiconify()
    except Exception:
        pass
    try:
        win.grab_set()
    except Exception:
        pass

    _present_modal_dialog(win, parent)
    parent.wait_window(win)
    return result[0] is True


def _login_movimenti_action_button_colors(db: dict) -> dict[str, tuple[str, str]]:
    """Colori effettivi come in Movimenti: token palette + default ``extras`` + ``_ui_color_overrides`` nel DB.
    Chiavi: ``accedi`` (Pulisci filtri, «Accedi», «Cancella valori»), ``pulisci`` (blu «Nuova utenza» /azione), ``stampa`` (rosso).

    Se ``ui_action_blue_*`` (Nuova utenza) risulta verde e ``mov_pulisci_accedi_*`` no, si scambiano
    le coppie così «Nuova utenza» resta nel blocco blu d’azione.
    """
    import cdc_ui_palette as cup
    import cdc_ui_theme as cut

    base = cup.get_base_palette_map_copy()
    extras = {
        "mov_btn_cerca_bg": "#2e7d32",
        "mov_btn_cerca_hover_bg": "#1b5e20",
        "mov_pulisci_accedi_bg": "#1565c0",
        "mov_pulisci_accedi_hover_bg": "#0d47a1",
        "ui_action_blue_bg": "#1565c0",
        "ui_action_blue_hover_bg": "#0d47a1",
        "mov_btn_print_search_bg": "#c62828",
        "mov_btn_print_search_hover_bg": "#8e0000",
    }
    raw = db.get(cut._OVERRIDES_KEY) or {}
    overrides: dict[str, str] = {}
    if isinstance(raw, dict):
        for k, v in raw.items():
            if isinstance(k, str) and isinstance(v, str):
                overrides[k] = v

    def _r(token: str) -> str:
        return cut.resolved_hex(token, base=base, extras=extras, overrides=overrides)

    def _norm_bg(h: str) -> str:
        return (cut.normalize_hex_color(h) or (h or "").strip().lower()).lower()

    def _rgb24(h: str) -> tuple[int, int, int]:
        n = _norm_bg(h).lstrip("#")
        if len(n) != 6:
            return 0, 0, 0
        return int(n[0:2], 16), int(n[2:4], 16), int(n[4:6], 16)

    def _looks_green_primary(bg: str) -> bool:
        """Verde dominante rispetto a R e B."""
        r, g, b = _rgb24(bg)
        return g >= max(r, b) + 15 and g >= 60

    accedi_pair = (_r("mov_pulisci_accedi_bg"), _r("mov_pulisci_accedi_hover_bg"))
    pulisci_pair = (_r("ui_action_blue_bg"), _r("ui_action_blue_hover_bg"))

    a_bg, p_bg = accedi_pair[0], pulisci_pair[0]
    green_on_nuova_token = _looks_green_primary(p_bg) and not _looks_green_primary(a_bg)
    if green_on_nuova_token:
        accedi_pair, pulisci_pair = pulisci_pair, accedi_pair

    return {
        "accedi": accedi_pair,
        "pulisci": pulisci_pair,
        "stampa": (_r("mov_btn_print_search_bg"), _r("mov_btn_print_search_hover_bg")),
    }


def run_login_dialog(
    parent: tk.Tk,
    db: dict,
    save: SaveFn,
    *,
    before_nuova_utenza: Callable[[], None] | None = None,
    after_prepare_nuova_utenza: Callable[[dict], None] | None = None,
    keep_window_on_success: Callable[[tk.Toplevel], None] | None = None,
) -> tuple[bool, AppSession | None]:
    """Finestra login. Ritorna (True, session) o (False, None)."""
    ensure_security(db)
    up = db["user_profile"]

    win = tk.Toplevel(parent)
    win.title(f"Accesso — Conti di casa {APP_VERSION}")
    try:
        win.configure(bg=CDC_LOGIN_WIN_BG)
    except Exception:
        pass
    win.resizable(False, False)
    # Evita il flash su macOS: la finestra non va mappata finché layout e geometria non sono pronti.
    try:
        win.withdraw()
    except Exception:
        pass

    _login_style = ttk.Style(win)
    try:
        _login_style.configure(
            "CdcLogin.TLabel",
            background=CDC_LOGIN_WIN_BG,
            foreground=CDC_TIPO_TASTI_BTN_FG,
        )
        _login_style.configure(
            "CdcLogin.TEntry",
            fieldbackground=CDC_TIPO_TASTI_FIELD_BG,
            foreground=CDC_TIPO_TASTI_BTN_FG,
            insertcolor=CDC_TIPO_TASTI_BTN_FG,
            font=("TkDefaultFont", 12),
        )
    except Exception:
        pass

    outer = tk.Frame(win, bg=CDC_LOGIN_WIN_BG)
    outer.pack(padx=14, pady=(8, _LOGIN_OUTER_PAD_BOTTOM_PX))
    outer.columnconfigure(0, weight=1)

    banner_wrap = tk.Frame(outer, bg=CDC_LOGIN_WIN_BG)
    banner_wrap.grid(row=0, column=0, sticky="ew", pady=(0, 8))
    banner_wrap.columnconfigure(0, weight=1)

    banner_inner = tk.Frame(
        banner_wrap,
        bg=CDC_LOGIN_WIN_BG,
        width=_LOGIN_BANNER_AREA_WIDTH,
        height=_LOGIN_BANNER_AREA_HEIGHT,
        highlightthickness=0,
    )
    banner_inner.grid(row=0, column=0, sticky="")
    banner_inner.grid_propagate(False)

    win._login_banner_photo = _load_login_euro_photo(max_side=_LOGIN_EURO_DISPLAY_MAX)

    euro_lbl = tk.Label(
        banner_inner,
        bg=CDC_LOGIN_WIN_BG,
        bd=0,
        highlightthickness=0,
    )
    if win._login_banner_photo is not None:
        euro_lbl.config(image=win._login_banner_photo)
        euro_lbl.image = win._login_banner_photo
    euro_lbl.place(relx=0.5, rely=0.5, anchor="center")

    frm = tk.Frame(outer, bg=CDC_LOGIN_WIN_BG)
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
    email_var = tk.StringVar(value=_login_prefill_email(up))
    ent_email = ttk.Entry(frm, textvariable=email_var, width=38, style="CdcLogin.TEntry")
    ent_email.grid(row=email_row + 1, column=0, columnspan=2, sticky="we", pady=(2, 8))

    ttk.Label(frm, text="Password", font=("TkDefaultFont", 12), style="CdcLogin.TLabel").grid(
        row=email_row + 2, column=0, sticky="w"
    )
    pw_var = tk.StringVar()
    ent_pw = ttk.Entry(frm, textvariable=pw_var, width=38, show="•", style="CdcLogin.TEntry")
    ent_pw.grid(row=email_row + 3, column=0, columnspan=2, sticky="we", pady=(2, 6))

    out: list[tuple[bool, AppSession | None]] = [(False, None)]
    done_var = tk.BooleanVar(master=parent, value=False)
    success_in_progress: list[bool] = [False]

    backdoor = _BackdoorState()

    def _finish_success(sess: AppSession) -> None:
        if success_in_progress[0]:
            return
        success_in_progress[0] = True
        out[0] = (True, sess)
        if keep_window_on_success is None:
            win.destroy()
            return
        try:
            win.grab_release()
        except Exception:
            pass
        try:
            win.protocol("WM_DELETE_WINDOW", lambda: None)
        except Exception:
            pass
        try:
            win.configure(cursor="watch")
            for child in win.winfo_children():
                _disable_login_widget_tree(child)
        except Exception:
            pass
        _show_login_loading_indicator()
        try:
            win.update_idletasks()
        except Exception:
            pass
        keep_window_on_success(win)
        done_var.set(True)

    def _finish_cancel() -> None:
        out[0] = (False, None)
        try:
            win.destroy()
        finally:
            try:
                done_var.set(True)
            except Exception:
                pass

    def _disable_login_widget_tree(widget: tk.Misc) -> None:
        if widget is loading_row:
            return
        try:
            widget.configure(state="disabled")
        except Exception:
            pass
        try:
            widget.configure(cursor="watch")
        except Exception:
            pass
        try:
            for child in widget.winfo_children():
                _disable_login_widget_tree(child)
        except Exception:
            pass

    def do_login() -> None:
        if success_in_progress[0]:
            return
        ensure_security(db)
        up_now = db["user_profile"]
        if not (up_now.get("password_hash") or "").strip():
            messagebox.showerror("Accesso", "Profilo non inizializzato.")
            return
        em = (email_var.get() or "").strip().lower()
        pw = pw_var.get() or ""
        if not em or not pw:
            messagebox.showerror("Accesso", "Inserisci email e password.")
            return
        if em != (up_now.get("email") or "").strip().lower():
            messagebox.showerror("Accesso", "Email non riconosciuta.")
            return
        if not verify_password(up_now, pw):
            messagebox.showerror("Accesso", "Password non corretta.")
            return
        verified = bool(up_now.get("registration_verified"))
        sess = AppSession(
            is_registered=verified,
            entered_via_backdoor=False,
            user_email=em,
        )
        _finish_success(sess)

    def do_nuova_utenza() -> None:
        if success_in_progress[0]:
            return
        if not messagebox.askyesno(
            "Nuova utenza",
            "Si crea un nuovo profilo di accesso (nome visualizzato, email e password, come al primo accesso).\n\n"
            "L’utenza che stai lasciando resta nei suoi file: le sue impostazioni (posta, sicurezza, "
            "registrazioni periodiche) restano legate a quell’account nel file .enc dedicato.\n"
            "Per la nuova utenza le opzioni ripartono vuote o predefinite e vanno configurate di nuovo in Opzioni.\n"
            "I dati contabili (anni, registrazioni, piano conti) vengono azzerati; si ripopolano solo "
            "con «Ricarica importi legacy» in Opzioni se lo attivi.\n\n"
            "Continuare?",
            parent=win,
        ):
            return
        if before_nuova_utenza is not None:
            try:
                before_nuova_utenza()
            except Exception as exc:
                messagebox.showerror(
                    "Nuova utenza",
                    f"Salvataggio dell’utenza precedente sul suo file dati non riuscito:\n{exc}",
                    parent=win,
                )
                return
        prepare_database_for_nuova_utenza(db)
        if after_prepare_nuova_utenza is not None:
            after_prepare_nuova_utenza(db)
        try:
            save()
        except Exception as exc:
            messagebox.showerror("Nuova utenza", f"Salvataggio non riuscito:\n{exc}", parent=win)
            return
        if not run_first_access_wizard_if_needed(parent, db, save):
            messagebox.showwarning(
                "Nuova utenza",
                "Primo accesso non completato.\n"
                "Alla prossima apertura potrai completare il profilo o usare «Nuova utenza» di nuovo.",
                parent=win,
            )
            return
        ensure_security(db)
        try:
            email_var.set(_login_prefill_email(db["user_profile"]))
        except Exception:
            email_var.set((db.get("user_profile") or {}).get("email") or "")
        try:
            pw_var.set("")
        except Exception:
            pass
        messagebox.showinfo(
            "Nuova utenza",
            "Profilo di accesso aggiornato: accedi con la nuova email e password.\n\n"
            "Le impostazioni dell’account precedente restano sul relativo file dati (quell’utenza). "
            "Per questa nuova utenza configura in Opzioni posta, sicurezza e le altre opzioni.\n"
            "I dati contabili sono vuoti finché non usi «Ricarica importi legacy» in Opzioni.",
            parent=win,
        )

    def do_backdoor() -> None:
        """Ctrl+Z poi Ctrl+X: sessione legata all’email nel campo userid; ``is_registered`` dal profilo dopo migrazione."""
        if success_in_progress[0]:
            return
        ensure_security(db)
        em_field = (email_var.get() or "").strip().lower()
        if not em_field or "@" not in em_field:
            messagebox.showerror(
                "Accesso tecnico",
                "Inserisci nel campo email (userid) l’utenza con cui entrare.",
                parent=win,
            )
            return
        up_now = db["user_profile"]
        prof_em = (up_now.get("email") or "").strip().lower()
        if prof_em == em_field:
            verified = bool(up_now.get("registration_verified"))
        else:
            # DB in RAM è di un altro account: la sessione userà ``user_email`` per ricaricare il .enc giusto.
            verified = False
        sess = AppSession(
            is_registered=verified,
            entered_via_backdoor=True,
            user_email=em_field,
        )
        _finish_success(sess)

    def on_ctrl_z(_e: tk.Event) -> str | None:
        backdoor.mark_z()
        return "break"

    def on_ctrl_x(_e: tk.Event) -> str | None:
        if backdoor.consume_for_backdoor():
            do_backdoor()
        return "break"

    rowb = tk.Frame(frm, bg=CDC_LOGIN_WIN_BG)
    rowb.grid(row=email_row + 4, column=0, columnspan=2, sticky="we", pady=(2, 0))
    rowb.columnconfigure(0, weight=1)
    rowb.columnconfigure(2, weight=1)
    btn_bar = tk.Frame(rowb, bg=CDC_LOGIN_WIN_BG)
    btn_bar.grid(row=0, column=1, sticky="")

    _lm = _login_movimenti_action_button_colors(db)
    acc_bg, acc_act = _lm["accedi"]
    nuo_bg, nuo_act = _lm["pulisci"]
    esc_bg, esc_act = _lm["stampa"]

    def _login_action_label(
        parent: tk.Misc,
        text: str,
        command: Callable[[], None],
        *,
        width_chars: int | None = None,
        btn_bg: str | None = None,
        btn_active_bg: str | None = None,
        btn_fg: str | None = None,
    ) -> tk.Label:
        bg = btn_bg if btn_bg is not None else _LOGIN_BTN_BG
        bg_act = btn_active_bg if btn_active_bg is not None else _LOGIN_BTN_ACTIVE_BG
        fg = btn_fg if btn_fg is not None else _LOGIN_BTN_FG
        kw: dict[str, Any] = {
            "master": parent,
            "text": text,
            "font": ("TkDefaultFont", 11, "bold"),
            "bg": bg,
            "fg": fg,
            "padx": 14,
            "pady": 7,
            "cursor": "hand2",
            "relief": tk.RAISED,
            "bd": CDC_TIPO_TASTI_BTN_BD,
            "highlightthickness": 0,
        }
        if width_chars is not None:
            kw["width"] = width_chars
        lb = tk.Label(**kw)

        def _enter(_e: tk.Event | None = None) -> None:
            lb.configure(bg=bg_act)

        def _leave(_e: tk.Event | None = None) -> None:
            lb.configure(bg=bg)

        def _click(_e: tk.Event) -> None:
            command()

        lb.bind("<Enter>", _enter)
        lb.bind("<Leave>", _leave)
        lb.bind("<Button-1>", _click)
        return lb

    _btn_pad_between = (0, 8)
    _login_action_label(
        btn_bar,
        "Accedi",
        do_login,
        width_chars=_LOGIN_BTN_WIDTH_ACCEDI_CHARS,
        btn_bg=acc_bg,
        btn_active_bg=acc_act,
        btn_fg="#ffffff",
    ).pack(side=tk.LEFT, padx=_btn_pad_between)
    _login_action_label(
        btn_bar,
        "Nuova utenza",
        do_nuova_utenza,
        btn_bg=nuo_bg,
        btn_active_bg=nuo_act,
        btn_fg="#ffffff",
    ).pack(side=tk.LEFT, padx=_btn_pad_between)
    _login_action_label(
        btn_bar,
        "Esci",
        _finish_cancel,
        width_chars=_LOGIN_BTN_WIDTH_ACCEDI_CHARS,
        btn_bg=esc_bg,
        btn_active_bg=esc_act,
        btn_fg="#ffffff",
    ).pack(side=tk.LEFT)

    loading_row = tk.Frame(frm, bg=CDC_LOGIN_WIN_BG)
    loading_row.columnconfigure(0, weight=1)
    loading_label = ttk.Label(
        loading_row,
        text="Caricamento in corso...",
        font=("TkDefaultFont", 11, "bold"),
        style="CdcLogin.TLabel",
    )
    loading_label.grid(row=0, column=0, sticky="", pady=(8, 4))
    loading_progress = ttk.Progressbar(
        loading_row,
        mode="indeterminate",
        length=220,
    )
    loading_progress.grid(row=1, column=0, sticky="", pady=(0, 2))

    def _show_login_loading_indicator() -> None:
        try:
            loading_row.grid(row=email_row + 5, column=0, columnspan=2, sticky="we", pady=(4, 0))
            loading_progress.start(12)
            win.update_idletasks()
            sw = max(1, int(win.winfo_screenwidth()))
            sh = max(1, int(win.winfo_screenheight()))
            w = max(int(win.winfo_width()), int(win.winfo_reqwidth()), _LOGIN_WIN_MIN_W)
            h = max(int(win.winfo_height()), int(win.winfo_reqheight()), _LOGIN_WIN_MIN_H)
            w = min(w, int(sw * 0.92))
            h = min(h, int(sh * 0.88))
            x = max(0, (sw - w) // 2)
            y = max(0, (sh - h) // 3)
            win.geometry(f"{w}x{h}+{x}+{y}")
            win.minsize(w, h)
            win.lift()
            win.update()
        except Exception:
            pass

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
        _finish_cancel()

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

    try:
        win.deiconify()
    except Exception:
        pass
    try:
        win.grab_set()
    except Exception:
        pass

    _present_modal_dialog(win, parent)
    try:
        ent_pw.focus_set()
    except Exception:
        pass
    parent.wait_variable(done_var) if keep_window_on_success is not None else parent.wait_window(win)
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
