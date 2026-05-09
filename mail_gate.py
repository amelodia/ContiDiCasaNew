"""
All'avvio: configurazione e verifica posta prima di login / primo accesso,
così le notifiche SMTP (registrazione) possono essere inviate subito dopo il wizard.
"""
from __future__ import annotations

import tkinter as tk
from collections.abc import Callable
from tkinter import messagebox, ttk
from typing import Any

import email_client
from window_focus import present_window

SaveFn = Callable[[], None]


def _security_config(db: dict) -> dict[str, Any]:
    raw = db.get("security_config")
    if not isinstance(raw, dict):
        raw = {}
        db["security_config"] = raw
    return raw


def is_mail_ready_for_notifications(db: dict) -> bool:
    """True se la posta è utilizzabile senza aprire il wizard all'avvio.

    Basta che SMTP/IMAP e credenziali siano impostati nel DB; non si richiede a ogni avvio
    di aver ripetuto «Verifica connessione» (``email_verified_ok`` resta utile in Opzioni come promemoria).
    """
    return email_client.is_app_mail_configured(db)


def run_startup_mail_gate(parent: tk.Misc, db: dict, save: SaveFn) -> bool:
    email_client.ensure_email_settings(db)
    _security_config(db)
    if is_mail_ready_for_notifications(db):
        return True

    win = tk.Toplevel(parent)
    win.title("Conti di casa — Configurazione posta")
    win.resizable(True, False)
    try:
        win.withdraw()
    except Exception:
        pass
    frm = ttk.Frame(win, padding=14)
    frm.pack(fill=tk.BOTH, expand=True)

    ttk.Label(
        frm,
        text=(
            "Configura e verifica la posta prima di accedere.\n"
            "Serve per inviare le notifiche di registrazione e leggere le conferme via IMAP."
        ),
        wraplength=520,
    ).grid(row=0, column=0, columnspan=4, sticky="w", pady=(0, 10))

    admin_var = tk.StringVar()
    smtp_host_var = tk.StringVar()
    smtp_port_var = tk.StringVar(value="587")
    smtp_implicit_var = tk.BooleanVar(value=False)
    smtp_starttls_var = tk.BooleanVar(value=True)
    imap_host_var = tk.StringVar()
    imap_port_var = tk.StringVar(value="993")
    imap_ssl_var = tk.BooleanVar(value=True)
    ssl_verify_var = tk.BooleanVar(value=True)
    user_var = tk.StringVar()
    pw_var = tk.StringVar()
    from_var = tk.StringVar()

    def _load_from_db() -> None:
        email_client.ensure_email_settings(db)
        s = db["email_settings"]
        sc = _security_config(db)
        admin_var.set((sc.get("admin_notify_email") or "").strip())
        smtp_host_var.set((s.get("smtp_host") or "").strip())
        smtp_port_var.set(str(int(s.get("smtp_port") or 587)))
        smtp_implicit_var.set(bool(s.get("smtp_implicit_ssl")))
        smtp_starttls_var.set(bool(s.get("smtp_use_starttls", True)))
        imap_host_var.set((s.get("imap_host") or "").strip())
        imap_port_var.set(str(int(s.get("imap_port") or 993)))
        imap_ssl_var.set(bool(s.get("imap_use_ssl", True)))
        ssl_verify_var.set(bool(s.get("ssl_verify_certificates", True)))
        user_var.set((s.get("username") or "").strip())
        pw_var.set(s.get("password") or "")
        from_var.set((s.get("from_address") or "").strip())

    def _apply_to_db() -> None:
        email_client.ensure_email_settings(db)
        s = db["email_settings"]
        sc = _security_config(db)
        sc["admin_notify_email"] = (admin_var.get() or "").strip()
        s["smtp_host"] = (smtp_host_var.get() or "").strip()
        try:
            s["smtp_port"] = int((smtp_port_var.get() or "587").strip())
        except ValueError:
            s["smtp_port"] = 587
        s["smtp_implicit_ssl"] = bool(smtp_implicit_var.get())
        s["smtp_use_starttls"] = bool(smtp_starttls_var.get())
        s["imap_host"] = (imap_host_var.get() or "").strip()
        try:
            s["imap_port"] = int((imap_port_var.get() or "993").strip())
        except ValueError:
            s["imap_port"] = 993
        s["imap_use_ssl"] = bool(imap_ssl_var.get())
        s["ssl_verify_certificates"] = bool(ssl_verify_var.get())
        s["username"] = (user_var.get() or "").strip()
        s["password"] = pw_var.get() or ""
        s["from_address"] = (from_var.get() or "").strip()

    _load_from_db()

    r = 1
    ttk.Label(frm, text="Email amministratore (riceve le notifiche)").grid(row=r, column=0, columnspan=4, sticky="w")
    r += 1
    ttk.Entry(frm, textvariable=admin_var, width=58).grid(row=r, column=0, columnspan=4, sticky="we", pady=(2, 8))
    r += 1
    ttk.Label(frm, text="SMTP server").grid(row=r, column=0, sticky="w")
    ttk.Entry(frm, textvariable=smtp_host_var, width=28).grid(row=r, column=1, sticky="we", padx=(6, 4))
    ttk.Label(frm, text="Porta").grid(row=r, column=2, sticky="e")
    ttk.Entry(frm, textvariable=smtp_port_var, width=6).grid(row=r, column=3, sticky="w")
    r += 1
    ttk.Checkbutton(frm, text="SMTP SSL 465", variable=smtp_implicit_var).grid(row=r, column=0, columnspan=2, sticky="w")
    ttk.Checkbutton(frm, text="STARTTLS", variable=smtp_starttls_var).grid(row=r, column=2, columnspan=2, sticky="w")
    r += 1
    ttk.Label(frm, text="IMAP server").grid(row=r, column=0, sticky="w", pady=(6, 0))
    ttk.Entry(frm, textvariable=imap_host_var, width=28).grid(row=r, column=1, sticky="we", padx=(6, 4), pady=(6, 0))
    ttk.Label(frm, text="Porta").grid(row=r, column=2, sticky="e", pady=(6, 0))
    ttk.Entry(frm, textvariable=imap_port_var, width=6).grid(row=r, column=3, sticky="w", pady=(6, 0))
    r += 1
    ttk.Checkbutton(frm, text="IMAP SSL", variable=imap_ssl_var).grid(row=r, column=0, columnspan=2, sticky="w")
    ttk.Checkbutton(frm, text="Verifica certificati SSL", variable=ssl_verify_var).grid(row=r, column=2, columnspan=2, sticky="w")
    r += 1
    ttk.Label(frm, text="Utente (email account)").grid(row=r, column=0, columnspan=4, sticky="w", pady=(8, 0))
    r += 1
    ttk.Entry(frm, textvariable=user_var, width=58).grid(row=r, column=0, columnspan=4, sticky="we")
    r += 1
    ttk.Label(frm, text="Password (Gmail: password per le app)").grid(row=r, column=0, columnspan=2, sticky="w", pady=(4, 0))
    ttk.Entry(frm, textvariable=pw_var, width=32, show="•").grid(row=r, column=2, columnspan=2, sticky="w", pady=(4, 0))
    r += 1
    ttk.Label(frm, text="Mittente (opz.)").grid(row=r, column=0, sticky="w", pady=(4, 0))
    ttk.Entry(frm, textvariable=from_var, width=40).grid(row=r, column=1, columnspan=3, sticky="w", pady=(4, 0))
    r += 1

    status = tk.StringVar(value="Compila i campi e premi «Verifica connessione».")
    ttk.Label(frm, textvariable=status, wraplength=520).grid(row=r, column=0, columnspan=4, sticky="w", pady=(10, 6))
    r += 1

    rowb = ttk.Frame(frm)
    rowb.grid(row=r, column=0, columnspan=4, sticky="we", pady=(4, 0))

    test_passed: list[bool] = [False]
    outcome: list[bool | None] = [None]

    btn_continue = ttk.Button(rowb, text="Continua", state="disabled")

    def do_verify() -> None:
        _apply_to_db()
        try:
            save()
        except Exception as exc:
            messagebox.showerror("Posta", f"Salvataggio non riuscito:\n{exc}", parent=win)
            return
        ok, msg = email_client.test_email_configuration(db)
        if ok:
            test_passed[0] = True
            _security_config(db)["email_verified_ok"] = True
            try:
                save()
            except Exception as exc:
                messagebox.showerror("Posta", str(exc), parent=win)
                return
            status.set("Verifica riuscita. Premi «Continua».")
            btn_continue.state(["!disabled"])
            messagebox.showinfo("Posta", msg, parent=win)
        else:
            test_passed[0] = False
            _security_config(db)["email_verified_ok"] = False
            status.set("Verifica non riuscita. Correggi i dati e riprova.")
            messagebox.showerror("Verifica posta", msg, parent=win)

    def do_continue() -> None:
        if not test_passed[0]:
            messagebox.showwarning(
                "Posta",
                "Esegui prima «Verifica connessione» con esito positivo.",
                parent=win,
            )
            return
        _apply_to_db()
        try:
            save()
        except Exception as exc:
            messagebox.showerror("Posta", str(exc), parent=win)
            return
        outcome[0] = True
        win.destroy()

    def do_skip() -> None:
        if messagebox.askyesno(
            "Posta non verificata",
            "Senza posta verificata non potrai inviare le notifiche di registrazione "
            "né ricevere conferme via IMAP.\n\n"
            "Procedere comunque?",
            parent=win,
        ):
            outcome[0] = True
            win.destroy()

    def on_close() -> None:
        if messagebox.askyesno(
            "Uscita",
            "Chiudere l'applicazione senza completare la configurazione posta?",
            parent=win,
        ):
            outcome[0] = False
            win.destroy()

    ttk.Button(rowb, text="Verifica connessione", command=do_verify).pack(side=tk.LEFT, padx=(0, 8))
    btn_continue.configure(command=do_continue)
    btn_continue.pack(side=tk.LEFT, padx=(0, 8))
    ttk.Button(rowb, text="Salta (sconsigliato)", command=do_skip).pack(side=tk.LEFT)

    win.protocol("WM_DELETE_WINDOW", on_close)
    frm.columnconfigure(1, weight=1)

    try:
        win.update_idletasks()
        ww = min(560, max(520, win.winfo_reqwidth()))
        wh = win.winfo_reqheight()
        sw = win.winfo_screenwidth()
        sh = win.winfo_screenheight()
        win.geometry(f"{ww}x{wh}+{(sw - ww) // 2}+{(sh - wh) // 3}")
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

    present_window(win, parent)

    parent.wait_window(win)
    return outcome[0] is True
